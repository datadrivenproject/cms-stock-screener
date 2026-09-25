import os
import sys
import math
import time
import io
import requests
import pandas as pd
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from universe_1500 import build_universe as build_composite_universe
from telegram_notify import send_telegram

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

# ============================================================
# CMS / BUSINESS QUANT API DESIGN NOTE — DO NOT REMOVE
# ============================================================
# IMPORTANT:
# 1) REQUEST_BATCH is the number of tickers packed into ONE BQ API request.
#    It is NOT the daily API request quota/rate limit.
# 2) CMS previously designed BQ multi-ticker requests around up to 100
#    tickers/request when the /quotes endpoint supports it.
# 3) Always minimize API calls: group tickers that share the same missing
#    date window, then request the largest provider-supported ticker batch.
# 4) TRUE INCREMENTAL remains mandatory:
#       existing ticker -> fetch ONLY latest_trade_date + 1 through till_date
#       new/no-history ticker -> SKIP here; use separate bootstrap loader
# 5) Before changing this value in the future, verify the CURRENT BQ /quotes
#    per-request ticker limit. Do NOT confuse it with daily/monthly quota.
#
# Current CMS intended batch size: 100 tickers per request.
REQUEST_BATCH = 100
DB_BATCH = 500

# Be deliberately gentle with Business Quant.
REQUEST_PAUSE_SECONDS = 10.0

# 429 backoff. Retry-After header is honored when present.
MAX_RETRIES = 2
BACKOFF_SECONDS = [15, 30]

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
    Fast daily status check.
    HARD RULES:
      - never scan historical data here;
      - 100 tickers per request;
      - fetch only the single latest stored trade_date for each ticker.
    """
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    counts = Counter()
    latest = {}

    # PostgREST cannot express "latest row per ticker" cheaply on the raw table.
    # For the daily job, query only today's/recent dates one day at a time,
    # newest first. Once a ticker is found, it is removed from later checks.
    now_et = datetime.now(ZoneInfo("America/New_York")).date()
    check_dates = [(now_et - timedelta(days=i)).isoformat() for i in range(0, 5)]
    remaining = set(tickers)

    for d in check_dates:
        if not remaining:
            break
        remaining_list = [t for t in tickers if t in remaining]
        for bno, batch in enumerate(chunks(remaining_list, 100), 1):
            filt = "in.(" + ",".join(batch) + ")"
            r = requests.get(
                url,
                params={
                    "select": "ticker,trade_date",
                    "ticker": filt,
                    "trade_date": f"eq.{d}",
                },
                headers=sb_headers(key),
                timeout=30,
            )
            r.raise_for_status()
            for row in r.json():
                t = str(row.get("ticker", "")).upper()
                if t and t in remaining:
                    latest[t] = d
                    counts[t] = 1
                    remaining.discard(t)

        print(f"Supabase latest-date check {d}: found={len(latest)}, remaining={len(remaining)}")

    return counts, latest

def next_calendar_day(yyyy_mm_dd):
    d = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").date()
    return (d + timedelta(days=1)).isoformat()


def today_iso():
    """
    Upper bound for settled EOD data.

    On Saturday/Sunday, use the most recent weekday instead of today's
    calendar date. This avoids asking Business Quant for weekend dates.
    US market holidays are harmless here: EOD mode simply returns no bar
    for a non-trading weekday.
    """
    # GitHub runners use UTC.  CMS EOD dates must follow the US market,
    # otherwise an evening ET run can accidentally request tomorrow's bar.
    now_et = datetime.now(ZoneInfo("America/New_York"))
    d = now_et.date()

    # Before the regular US close, today's EOD bar is not settled yet.
    if now_et.hour < 16:
        d -= timedelta(days=1)

    while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        d -= timedelta(days=1)

    # BQ till_date is the inclusive end date. After the US close,
    # request through the current settled trading date itself.
    return d.isoformat()


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
                # Do not let one stale ticker block the entire 529-stock resume.
                # Retry briefly once; on the final 429, fail this batch so the
                # caller records it and immediately continues to the next batch.
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(
                        f"Business Quant 429 after {MAX_RETRIES} attempts "
                        f"[{from_date} -> {till_date}] "
                        f"tickers={','.join(batch)}"
                    )

                retry_after = r.headers.get("Retry-After")
                try:
                    server_wait = int(float(retry_after)) if retry_after else BACKOFF_SECONDS[attempt - 1]
                except Exception:
                    server_wait = BACKOFF_SECONDS[attempt - 1]

                # Keep resume jobs moving even if the provider sends a very long
                # Retry-After value.
                wait_s = max(server_wait, BACKOFF_SECONDS[attempt - 1])

                print(
                    f"  ⚠️ 429 Too Many Requests. "
                    f"等待 {wait_s} 秒后短暂重试 ({attempt}/{MAX_RETRIES})；"
                    f"若仍 429 将继续按退避时间重试..."
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
        return {
            str(ticker).upper().strip().replace(".", "-"): block
            for ticker, block in result.items()
        }

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

    tickers = build_composite_universe(verbose=True)

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

    # Freshness warning: a successful HTTP/API run is not the same as fresh EOD data.
    # till_date is the inclusive expected latest settled trading date.
    expected_latest = till_date
    if final_latest != "未知" and final_latest < expected_latest:
        print("\n" + "!" * 78)
        print(
            f"⚠️ 数据源尚未发布预期的最新 EOD 数据："
            f"预期交易日 {expected_latest}，数据库最新仅到 {final_latest}。"
        )
        print("⚠️ 本次 Pipeline 虽执行成功，但数据新鲜度未通过；请稍后重新运行增量更新。")
        alert = (
            "⚠️ 股票数据更新异常\\n"
            f"应更新至：{expected_latest}\\n"
            f"当前数据库：{final_latest}\\n"
            "数据源可能尚未发布最新日线，请稍后重跑。"
        )
        try:
            send_telegram(alert)
            print("📲 已发送 Telegram 数据新鲜度提醒。")
        except Exception as e:
            print(f"⚠️ Telegram 数据新鲜度提醒发送失败: {e}")
        print("!" * 78)
        # Hard freshness gate: never allow downstream selection to run on stale EOD.
        # Exit non-zero so GitHub Actions stops before adjusted OHLC / A selection.
        fail(
            f"数据新鲜度未通过：预期 {expected_latest}，"
            f"数据库最新 {final_latest}；停止后续 A 选股。"
        )

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
