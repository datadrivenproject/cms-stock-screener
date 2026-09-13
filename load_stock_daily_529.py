import os
import sys
import math
import time
import io
import requests
import pandas as pd
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta

# =========================================================
# CMS DAILY DATA ENGINE — TRUE INCREMENTAL ONLY
#
# HARD RULE:
#   - This DAILY updater NEVER requests 1y / historical history.
#   - It reads each ticker's latest Supabase trade_date.
#   - It requests ONLY dates after that date:
#         from_date = latest_date + 1 calendar day
#         till_date = today
#   - It writes ONLY genuinely new ticker + trade_date rows.
#   - A ticker with no existing history is SKIPPED here and must
#     be handled separately by a one-time bootstrap/history loader.
# =========================================================

BQ_URL = "https://data.businessquant.com/quotes"

REQUEST_BATCH = 10
DB_BATCH = 500

# Be deliberately gentle with Business Quant.
REQUEST_PAUSE_SECONDS = 4.0

# 429 backoff. Retry-After header is honored when present.
MAX_RETRIES = 5
BACKOFF_SECONDS = [30, 60, 120, 240, 300]

MIN_VALID_DAYS = 200

SP500_SOURCES = [
    "https://raw.githubusercontent.com/chinobing/historical_sp500_constituents/refs/heads/main/sp500_constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
]

CORE_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","ORCL","IBM","DELL","HPE","SMCI",
    "CRM","ADBE","NOW","PLTR","PATH","CRWD","PANW","FTNT","DDOG","NET","SNOW","MDB","ZS","OKTA","TEAM",
    "QCOM","MU","INTC","ARM","MRVL","AMAT","LRCX","KLAC","ON","MCHP",
    "JPM","BAC","WFC","GS","MS","V","MA","AXP","PYPL","COIN","HOOD","SOFI","XYZ","NU","IBKR",
    "LLY","UNH","ABBV","MRK","AMGN","JNJ","PFE","GILD","ISRG","TMO","TEM","VEEV","REGN","VRTX","DXCM",
    "XOM","CVX","COP","CAT","GE","BA","RTX","LMT","ETN","VRT","PLUG","FCX","SLB","FSLR","CEG",
    "WMT","COST","HD","DIS","UBER","ABNB","DASH","BKNG","SHOP","MELI","RBLX","SPOT","ROKU","DUOL","RDDT",
    "CRCL","APP","RKLB","ASTS","IONQ","RGTI","SOUN","HIMS","CAVA","CVNA"
]


def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def env(name):
    v = os.getenv(name, "").strip()
    if not v:
        fail(f"缺少 GitHub Secret: {name}")
    return v


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def fnum(v):
    if v in (None, ""):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def inum(v):
    if v in (None, ""):
        return None
    return int(float(v))


def valid(row):
    o, h, l, c, v = [row[k] for k in ("open", "high", "low", "close", "volume")]
    if any(x is None for x in (o, h, l, c, v)):
        return False
    return (
        min(o, h, l, c) > 0
        and v >= 0
        and h >= max(o, l, c)
        and l <= min(o, h, c)
    )


def get_sp500_tickers():
    for url in SP500_SOURCES:
        try:
            r = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 CMS-DAILY-INCREMENTAL"},
            )
            print(f"S&P500 source HTTP {r.status_code}: {url}")
            if not r.ok or not r.text.strip():
                continue

            df = pd.read_csv(io.StringIO(r.text))
            symbol_col = next(
                (
                    c
                    for c in df.columns
                    if str(c).strip().lower() in {"symbol", "ticker", "tickers"}
                ),
                None,
            )
            if symbol_col is None:
                continue

            tickers = (
                df[symbol_col]
                .astype(str)
                .str.upper()
                .str.strip()
                .str.replace(".", "-", regex=False)
                .tolist()
            )
            tickers = list(dict.fromkeys(t for t in tickers if t and t != "NAN"))

            if len(tickers) >= 450:
                return tickers

        except Exception as e:
            print("⚠️ S&P500 source failed:", e)

    fail("无法取得有效 S&P 500 股票名单；本次停止。")


def build_universe():
    sp500 = get_sp500_tickers()
    universe = list(dict.fromkeys(sp500 + CORE_UNIVERSE))

    print(f"当前 S&P500 ticker: {len(sp500)}")
    print(f"CMS Core/watchlist: {len(CORE_UNIVERSE)}")
    print(f"去重后目标股票池: {len(universe)}")

    return universe


def sb_headers(key):
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def get_existing_status(base_url, key, tickers):
    """
    Read existing Supabase status for each ticker:
      counts[ticker] = number of stored rows
      latest[ticker] = latest stored trade_date
    """
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"

    counts = Counter()
    latest = {}

    for bno, batch in enumerate(chunks(tickers, 25), 1):
        filt = "in.(" + ",".join(batch) + ")"
        start = 0
        page_size = 1000

        while True:
            headers = dict(sb_headers(key))
            headers["Range"] = f"{start}-{start + page_size - 1}"

            r = requests.get(
                url,
                params={
                    "select": "ticker,trade_date",
                    "ticker": filt,
                    "order": "ticker.asc,trade_date.asc",
                },
                headers=headers,
                timeout=120,
            )

            if not r.ok:
                print(r.text[:1500])
                r.raise_for_status()

            page = r.json()

            for row in page:
                t = str(row.get("ticker", "")).upper()
                d = str(row.get("trade_date", ""))[:10]

                if t:
                    counts[t] += 1
                    if d and (t not in latest or d > latest[t]):
                        latest[t] = d

            if len(page) < page_size:
                break

            start += page_size

        print(f"Supabase status batch {bno}: {len(batch)} tickers")

    return counts, latest


def next_calendar_day(yyyy_mm_dd):
    d = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").date()
    return (d + timedelta(days=1)).isoformat()


def today_iso():
    # Explicit date bound required by Business Quant.
    # EOD mode only returns settled sessions, so weekends/holidays add nothing.
    return date.today().isoformat()


def fetch_batch_incremental(api_key, batch, from_date, till_date):
    """
    TRUE incremental Business Quant request.
    IMPORTANT: no `period` parameter anywhere in this function.

    Business Quant docs support:
      mode=eod
      from_date=YYYY-MM-DD
      till_date=YYYY-MM-DD
    """
    params = {
        "ticker": ",".join(batch),
        "mode": "eod",
        "from_date": from_date,
        "till_date": till_date,
        "limit": 100,
        "page": 1,
        "api_key": api_key,
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(BQ_URL, params=params, timeout=120)
            print(
                f"  Business Quant HTTP {r.status_code} "
                f"| {from_date} -> {till_date} | {len(batch)} tickers"
            )

            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait_s = int(float(retry_after)) if retry_after else BACKOFF_SECONDS[attempt - 1]
                except Exception:
                    wait_s = BACKOFF_SECONDS[attempt - 1]

                print(
                    f"  ⚠️ 429 Too Many Requests. "
                    f"等待 {wait_s} 秒后重试 ({attempt}/{MAX_RETRIES})..."
                )
                time.sleep(wait_s)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_error = e
            if attempt >= MAX_RETRIES:
                break

            wait_s = min(15 * attempt, 60)
            print(
                f"  ⚠️ 第 {attempt} 次请求失败: {e} "
                f"| 等待 {wait_s} 秒后重试..."
            )
            time.sleep(wait_s)

    if last_error is not None:
        raise last_error

    raise RuntimeError("Business Quant 请求失败")


def normalize_multi_ticker_result(result, batch):
    """
    Normalize BQ response into dict[ticker] -> block.
    """
    if isinstance(result, dict) and "metadata" in result and "data" in result:
        t = str(result.get("metadata", {}).get("ticker", batch[0])).upper()
        return {t: result}

    if isinstance(result, dict):
        return result

    return {}


def clean(ticker, block):
    raw = block.get("data", []) if isinstance(block, dict) else []

    if not raw:
        return []

    grouped = defaultdict(list)

    for x in raw:
        d = str(x.get("date", ""))[:10]
        if d:
            grouped[d].append(x)

    out = []
    conflicts = 0

    for d in sorted(grouped):
        norm = []

        for x in grouped[d]:
            try:
                norm.append(
                    {
                        "ticker": ticker,
                        "trade_date": d,
                        "open": fnum(x.get("open")),
                        "high": fnum(x.get("high")),
                        "low": fnum(x.get("low")),
                        "close": fnum(x.get("close")),
                        "volume": inum(x.get("volume")),
                        "source": "businessquant",
                    }
                )
            except Exception:
                pass

        good = [x for x in norm if valid(x)]

        if not good:
            continue

        if len(good) > 1:
            sig = {
                (x["open"], x["high"], x["low"], x["close"], x["volume"])
                for x in good
            }
            if len(sig) > 1:
                conflicts += 1

        out.append(good[-1])

    print(
        f"    {ticker}: raw={len(raw)} "
        f"unique={len(out)} conflict_dates={conflicts}"
    )

    return out


def upsert(base_url, key, rows):
    if not rows:
        print("ℹ️ 没有新行需要写入。")
        return

    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    total = math.ceil(len(rows) / DB_BATCH)

    for i, batch in enumerate(chunks(rows, DB_BATCH), 1):
        r = requests.post(
            url,
            params={"on_conflict": "ticker,trade_date"},
            headers=headers,
            json=batch,
            timeout=120,
        )

        print(
            f"  Supabase batch {i}/{total}: "
            f"HTTP {r.status_code} ({len(batch)} rows)"
        )

        if not r.ok:
            print(r.text[:2000])
            r.raise_for_status()


def verify(base_url, key, tickers):
    counts, latest = get_existing_status(base_url, key, tickers)

    dates = [d for d in latest.values() if d]
    global_latest = max(dates) if dates else "未知"

    sufficient = [
        (t, int(counts.get(t, 0)), latest.get(t, ""))
        for t in tickers
        if counts.get(t, 0) >= MIN_VALID_DAYS
    ]

    no_history = [
        t
        for t in tickers
        if counts.get(t, 0) == 0
    ]

    stale = [
        (t, latest.get(t, ""))
        for t in tickers
        if latest.get(t, "") and latest.get(t, "") < global_latest
    ]

    print("\n========== Supabase 验证 ==========")
    print(f"全库最新交易日: {global_latest}")
    print(
        f"有足够历史(>={MIN_VALID_DAYS}日): "
        f"{len(sufficient)} / {len(tickers)}"
    )

    if stale:
        print(f"⚠️ 落后于全库最新日期的股票: {len(stale)}")
        for x in stale[:50]:
            print(" ", x)

    if no_history:
        print(
            f"⚠️ 完全没有历史数据的股票: {len(no_history)} "
            f"(Daily updater 不会为它们拉1年历史)"
        )
        for t in no_history[:50]:
            print(" ", t)

    return counts, latest, global_latest


def main():
    print("=" * 78)
    print("CMS Data Engine — TRUE DAILY INCREMENTAL UPDATE")
    print("硬规则：每天只下载缺失/新增交易日；绝不在 daily job 拉 1 年历史。")
    print("=" * 78)

    bq_key = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL 必须是项目基础 URL，不能包含 /rest/v1")

    tickers = build_universe()

    print("\n🔎 检查 Supabase 当前最后日期...")
    counts, latest = get_existing_status(sb_url, sb_key, tickers)

    global_dates = [d for d in latest.values() if d]
    current_global_latest = max(global_dates) if global_dates else "未知"

    print("\n========== 更新前 ==========")
    print(f"目标股票池: {len(tickers)}")
    print(f"stock_daily 全库最新日期: {current_global_latest}")

    # -----------------------------------------------------
    # Build groups by exact missing start date.
    #
    # Example:
    #   CIEN latest 2026-09-08 -> from_date 2026-09-09
    #
    # Tickers with no history are deliberately skipped.
    # We do NOT silently fetch 1y in the daily job.
    # -----------------------------------------------------
    groups = defaultdict(list)
    skipped_no_history = []

    for t in tickers:
        last_date = latest.get(t)

        if not last_date:
            skipped_no_history.append(t)
            continue

        start_date = next_calendar_day(last_date)
        groups[start_date].append(t)

    till_date = today_iso()

    if skipped_no_history:
        print(
            f"\n⚠️ {len(skipped_no_history)} 只股票在 Supabase 完全没有历史。"
        )
        print(
            "Daily updater 将跳过它们，不会为了补历史而请求 1 年。"
        )
        print(
            "如需加入新股票，请单独运行一次性 bootstrap/history loader。"
        )

    all_new_rows = []
    failed = []

    print("\n========== TRUE INCREMENTAL REQUEST PLAN ==========")
    print(f"统一 till_date: {till_date}")

    for start_date in sorted(groups):
        group = groups[start_date]

        # If from_date is after today there is nothing to request.
        if start_date > till_date:
            print(
                f"✓ {len(group)} 只股票已无缺失日期 "
                f"(from {start_date} > today {till_date})"
            )
            continue

        print(
            f"\n📅 缺失窗口 {start_date} -> {till_date}: "
            f"{len(group)} 只股票"
        )

        batches = list(chunks(group, REQUEST_BATCH))

        for n, batch in enumerate(batches, 1):
            print(
                f"\n📥 BQ 增量请求 {n}/{len(batches)} "
                f"[{start_date} -> {till_date}]: "
                f"{', '.join(batch)}"
            )

            try:
                result = fetch_batch_incremental(
                    bq_key,
                    batch,
                    start_date,
                    till_date,
                )
            except Exception as e:
                print(f"❌ 本批请求最终失败: {e}")
                failed.extend(batch)
                # Still pause before next batch.
                time.sleep(REQUEST_PAUSE_SECONDS)
                continue

            result = normalize_multi_ticker_result(result, batch)

            for t in batch:
                block = result.get(t)
                rows = clean(t, block)

                # Final safety gate:
                # even if provider returns an unexpected older row,
                # never write anything <= that ticker's existing latest date.
                last_date = latest.get(t, "")
                new_rows = [
                    r for r in rows
                    if r["trade_date"] > last_date
                ]

                if new_rows:
                    print(
                        f"    ✅ {t}: 新增 {len(new_rows)} 日 "
                        f"{new_rows[0]['trade_date']} -> "
                        f"{new_rows[-1]['trade_date']}"
                    )
                    all_new_rows.extend(new_rows)
                else:
                    print(f"    ✓ {t}: 当前无新增交易日")

            # Gentle pacing to avoid 429.
            if n < len(batches):
                print(
                    f"  ⏳ 主动等待 {REQUEST_PAUSE_SECONDS:.0f} 秒，"
                    "避免 Business Quant 限流..."
                )
                time.sleep(REQUEST_PAUSE_SECONDS)

    # Exact duplicate safety.
    keys = [(r["ticker"], r["trade_date"]) for r in all_new_rows]

    if len(keys) != len(set(keys)):
        fail("清洗后仍存在 ticker + trade_date 重复")

    print("\n========== 本轮下载结果 ==========")
    print(f"新增唯一日K: {len(all_new_rows)} 条")
    print(
        f"涉及股票: "
        f"{len(set(r['ticker'] for r in all_new_rows)) if all_new_rows else 0}"
    )

    if failed:
        print(
            f"⚠️ 最终失败股票: {len(set(failed))}"
        )
        print(", ".join(sorted(set(failed))))

    if all_new_rows:
        print("\n📤 写入 Supabase stock_daily...")
        upsert(sb_url, sb_key, all_new_rows)
    else:
        print("\n✅ 没有发现需要写入的新交易日。")

    _, _, final_latest = verify(sb_url, sb_key, tickers)

    print("\n" + "=" * 78)
    print(f"✅ Daily incremental update 完成")
    print(f"Supabase stock_daily 最新交易日：{final_latest}")
    print("")
    print("下一步：")
    print("  python adjust_stock_daily_529.py")
    print("")
    print("再次强调：本程序没有 PERIOD='1y'，")
    print("daily job 只使用 from_date / till_date 下载缺失交易日。")
    print("=" * 78)


if __name__ == "__main__":
    main()
