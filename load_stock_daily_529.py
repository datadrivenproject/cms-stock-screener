import os, sys, math, time, io, requests
import pandas as pd
from collections import defaultdict, Counter

BQ_URL = "https://data.businessquant.com/quotes"
PERIOD = "1y"
REQUEST_BATCH = 10
DB_BATCH = 500
MAX_RETRIES = 3
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
    o, h, l, c, v = [row[k] for k in ("open","high","low","close","volume")]
    if any(x is None for x in (o,h,l,c,v)):
        return False
    return min(o,h,l,c) > 0 and v >= 0 and h >= max(o,l,c) and l <= min(o,h,c)

def get_sp500_tickers():
    for url in SP500_SOURCES:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0 CMS"})
            print(f"S&P500 source HTTP {r.status_code}: {url}")
            if not r.ok or not r.text.strip():
                continue
            df = pd.read_csv(io.StringIO(r.text))
            symbol_col = next((c for c in df.columns if str(c).strip().lower() in {"symbol","ticker","tickers"}), None)
            if symbol_col is None:
                continue
            tickers = (
                df[symbol_col].astype(str).str.upper().str.strip()
                .str.replace(".","-",regex=False).tolist()
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
        "Accept": "application/json"
    }

def get_existing_status(base_url, key, tickers):
    """
    返回每只股票：
      count = Supabase 已有日K条数
      latest = 最新 trade_date

    原程序只有 count，所以 >=200 日后永远不会再更新。
    """
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    counts = Counter()
    latest = {}

    for bno, batch in enumerate(chunks(tickers, 25), 1):
        filt = "in.(" + ",".join(batch) + ")"
        start, page_size = 0, 1000

        while True:
            h = dict(sb_headers(key))
            h["Range"] = f"{start}-{start+page_size-1}"
            r = requests.get(
                url,
                params={
                    "select": "ticker,trade_date",
                    "ticker": filt,
                    "order": "ticker.asc,trade_date.asc"
                },
                headers=h,
                timeout=120
            )
            if not r.ok:
                print(r.text[:1500])
                r.raise_for_status()

            page = r.json()
            for row in page:
                t = str(row.get("ticker","")).upper()
                d = str(row.get("trade_date",""))[:10]
                if t:
                    counts[t] += 1
                    if d and (t not in latest or d > latest[t]):
                        latest[t] = d

            if len(page) < page_size:
                break
            start += page_size

        print(f"Supabase status batch {bno}: {len(batch)} tickers")

    return counts, latest

def fetch_batch(api_key, batch):
    params = {
        "ticker": ",".join(batch),
        "mode": "eod",
        "period": PERIOD,
        "limit": 500,
        "page": 1,
        "api_key": api_key
    }
    last = None

    for attempt in range(1, MAX_RETRIES+1):
        try:
            r = requests.get(BQ_URL, params=params, timeout=120)
            print("  Business Quant HTTP", r.status_code)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            print(f"  ⚠️ 第 {attempt} 次请求失败: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(3*attempt)

    raise last

def clean(ticker, block):
    raw = block.get("data",[]) if isinstance(block,dict) else []
    if not raw:
        return []

    grouped = defaultdict(list)
    for x in raw:
        d = str(x.get("date",""))[:10]
        if d:
            grouped[d].append(x)

    out = []
    conflicts = 0

    for d in sorted(grouped):
        norm = []
        for x in grouped[d]:
            try:
                norm.append({
                    "ticker": ticker,
                    "trade_date": d,
                    "open": fnum(x.get("open")),
                    "high": fnum(x.get("high")),
                    "low": fnum(x.get("low")),
                    "close": fnum(x.get("close")),
                    "volume": inum(x.get("volume")),
                    "source": "businessquant"
                })
            except Exception:
                pass

        good = [x for x in norm if valid(x)]
        if not good:
            continue

        if len(good) > 1:
            sig = {(x["open"],x["high"],x["low"],x["close"],x["volume"]) for x in good}
            if len(sig) > 1:
                conflicts += 1

        out.append(good[-1])

    print(f"    {ticker}: raw={len(raw)} unique={len(out)} conflict_dates={conflicts}")
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
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    total = math.ceil(len(rows)/DB_BATCH)
    for i, batch in enumerate(chunks(rows, DB_BATCH), 1):
        r = requests.post(
            url,
            params={"on_conflict":"ticker,trade_date"},
            headers=headers,
            json=batch,
            timeout=120
        )
        print(f"  Supabase batch {i}/{total}: HTTP {r.status_code} ({len(batch)} rows)")
        if not r.ok:
            print(r.text[:2000])
            r.raise_for_status()

def verify(base_url, key, tickers):
    counts, latest = get_existing_status(base_url, key, tickers)

    good = [(t, int(counts.get(t,0)), latest.get(t,"")) for t in tickers if counts.get(t,0) >= MIN_VALID_DAYS]
    bad = [(t, int(counts.get(t,0)), latest.get(t,"")) for t in tickers if counts.get(t,0) < MIN_VALID_DAYS]

    dates = [d for d in latest.values() if d]
    global_latest = max(dates) if dates else "未知"

    print("\n========== Supabase 验证 ==========")
    print(f"全库最新交易日: {global_latest}")
    print(f"有足够一年原始日K(>={MIN_VALID_DAYS}日): {len(good)} / {len(tickers)}")

    stale = [(t, latest.get(t,"")) for t in tickers if latest.get(t,"") and latest.get(t,"") < global_latest]
    if stale:
        print(f"⚠️ 落后于全库最新日期的股票: {len(stale)}")
        for x in stale[:50]:
            print(" ", x)

    if bad:
        print(f"⚠️ 数据不足股票: {len(bad)}")
        for x in bad[:50]:
            print(" ", x)

    return good, bad, latest, global_latest

def main():
    print("="*76)
    print("CMS Data Engine — 500+ 股票池：历史补齐 + 每日增量更新")
    print(f"Source: Business Quant | 请求周期: {PERIOD}")
    print("="*76)

    bq_key = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL 必须是项目基础 URL，不能包含 /rest/v1")

    tickers = build_universe()

    print("\n🔎 检查 Supabase 当前状态...")
    counts, latest = get_existing_status(sb_url, sb_key, tickers)

    print("\n========== 当前状态 ==========")
    print(f"目标股票池: {len(tickers)}")
    dates = [d for d in latest.values() if d]
    if dates:
        print(f"当前 stock_daily 最新日期: {max(dates)}")
    else:
        print("当前 stock_daily 最新日期: 未知")

    # 关键修复：
    # 旧版：>=200天就完全跳过，因此数据库会永远停在某一天。
    # 新版：每天都检查全部股票；Business Quant 返回后，
    #       只保留 trade_date > 该 ticker 当前最新日期的新行。
    all_new_rows = []
    missing = []

    batches = list(chunks(tickers, REQUEST_BATCH))
    for n, batch in enumerate(batches, 1):
        print(f"\n📥 BQ 请求 {n}/{len(batches)}: {', '.join(batch)}")

        try:
            result = fetch_batch(bq_key, batch)
        except Exception as e:
            print(f"❌ 本批请求最终失败: {e}")
            missing.extend(batch)
            continue

        if isinstance(result,dict) and "metadata" in result and "data" in result:
            t = result.get("metadata",{}).get("ticker", batch[0])
            result = {t: result}

        for t in batch:
            block = result.get(t) if isinstance(result,dict) else None
            rows = clean(t, block)

            if not rows:
                print(f"    ⚠️ {t} 无有效数据")
                missing.append(t)
                continue

            last_date = latest.get(t, "")
            new_rows = [r for r in rows if (not last_date or r["trade_date"] > last_date)]

            # 新股票或历史不足时，仍允许补齐完整历史
            if counts.get(t,0) < MIN_VALID_DAYS:
                new_rows = rows

            if new_rows:
                print(f"    ✅ {t}: 新增 {len(new_rows)} 日，"
                      f"{new_rows[0]['trade_date']} -> {new_rows[-1]['trade_date']}")
                all_new_rows.extend(new_rows)
            else:
                print(f"    ✓ {t}: 已是最新，无新增交易日")

    keys = [(r["ticker"], r["trade_date"]) for r in all_new_rows]
    if len(keys) != len(set(keys)):
        fail("清洗后仍存在 ticker + trade_date 重复")

    print(f"\n📊 本轮新增日K: {len(all_new_rows)} 条")
    if missing:
        print("⚠️ 本轮无数据/请求失败:", ", ".join(sorted(set(missing))))

    if all_new_rows:
        print("\n📤 写入 Supabase stock_daily...")
        upsert(sb_url, sb_key, all_new_rows)
    else:
        print("\n✅ 没有发现需要写入的新交易日。")

    good, bad, latest2, global_latest = verify(sb_url, sb_key, tickers)

    print("\n" + "="*76)
    print(f"✅ 本轮结束。Supabase stock_daily 最新交易日：{global_latest}")
    print("")
    print("注意：如果 stock_daily 新增了交易日，仍需运行 adjust_stock_daily_529.py，")
    print("为新行生成 adj_open / adj_high / adj_low / adj_close。")
    print("之后再运行 CMS A 扫描。")
    print("="*76)

if __name__ == "__main__":
    main()
