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

BENCHMARKS_12 = [
    "SPY","XLK","XLV","XLF","XLY","XLP",
    "XLI","XLE","XLB","XLU","XLRE","XLC"
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
    if v in (None, ""): return None
    x = float(v)
    return x if math.isfinite(x) else None

def inum(v):
    if v in (None, ""): return None
    return int(float(v))

def valid(row):
    o,h,l,c,v = [row[k] for k in ("open","high","low","close","volume")]
    if any(x is None for x in (o,h,l,c,v)): return False
    return min(o,h,l,c)>0 and v>=0 and h>=max(o,l,c) and l<=min(o,h,c)

def get_sp500_tickers():
    for url in SP500_SOURCES:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0 CMS-A6-FINAL"})
            print(f"S&P500 source HTTP {r.status_code}: {url}")
            if not r.ok or not r.text.strip():
                continue
            df = pd.read_csv(io.StringIO(r.text))
            symbol_col = next((c for c in df.columns if str(c).strip().lower() in {"symbol","ticker","tickers"}), None)
            if symbol_col is None:
                continue
            tickers = (df[symbol_col].astype(str).str.upper().str.strip().str.replace(".","-",regex=False).tolist())
            tickers = list(dict.fromkeys(t for t in tickers if t and t!="NAN"))
            if len(tickers) >= 450:
                return tickers
        except Exception as e:
            print("⚠️ S&P500 source failed:", e)
    fail("无法取得有效 S&P 500 股票名单；本次停止。")

def build_universe():
    sp500 = get_sp500_tickers()
    stocks = list(dict.fromkeys(sp500 + CORE_UNIVERSE))
    universe = list(dict.fromkeys(stocks + BENCHMARKS_12))
    print(f"当前 S&P500 ticker: {len(sp500)}")
    print(f"CMS Core/watchlist: {len(CORE_UNIVERSE)}")
    print(f"A6 正式股票池(去重): {len(stocks)}")
    print(f"Benchmark ETFs: {len(BENCHMARKS_12)}")
    print(f"检查总 ticker: {len(universe)}")
    return universe

def sb_headers(key):
    return {"apikey":key,"Authorization":f"Bearer {key}","Accept":"application/json"}

def get_existing_counts(base_url, key, tickers):
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    counts = Counter()
    for bno, batch in enumerate(chunks(tickers,25),1):
        filt = "in.(" + ",".join(batch) + ")"
        start, page_size = 0, 1000
        while True:
            h = dict(sb_headers(key)); h["Range"] = f"{start}-{start+page_size-1}"
            r = requests.get(url, params={"select":"ticker,trade_date","ticker":filt,"order":"ticker.asc,trade_date.asc"}, headers=h, timeout=120)
            if not r.ok:
                print(r.text[:1500]); r.raise_for_status()
            page = r.json()
            for row in page:
                t = str(row.get("ticker","")).upper()
                if t: counts[t] += 1
            if len(page) < page_size: break
            start += page_size
        print(f"Supabase coverage batch {bno}: {len(batch)} tickers")
    return counts

def fetch_batch(api_key, batch):
    params = {"ticker":",".join(batch),"mode":"eod","period":PERIOD,"limit":500,"page":1,"api_key":api_key}
    last = None
    for attempt in range(1, MAX_RETRIES+1):
        try:
            r = requests.get(BQ_URL, params=params, timeout=120)
            print("  Business Quant HTTP", r.status_code)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last=e
            print(f"  ⚠️ 第 {attempt} 次请求失败: {e}")
            if attempt < MAX_RETRIES: time.sleep(3*attempt)
    raise last

def clean(ticker, block):
    raw = block.get("data",[]) if isinstance(block,dict) else []
    if not raw: return []
    grouped = defaultdict(list)
    for x in raw:
        d = str(x.get("date",""))[:10]
        if d: grouped[d].append(x)
    out=[]; conflicts=0
    for d in sorted(grouped):
        norm=[]
        for x in grouped[d]:
            try:
                norm.append({"ticker":ticker,"trade_date":d,"open":fnum(x.get("open")),"high":fnum(x.get("high")),
                             "low":fnum(x.get("low")),"close":fnum(x.get("close")),"volume":inum(x.get("volume")),
                             "source":"businessquant"})
            except Exception:
                pass
        good=[x for x in norm if valid(x)]
        if not good: continue
        if len(good)>1:
            sig={(x["open"],x["high"],x["low"],x["close"],x["volume"]) for x in good}
            if len(sig)>1: conflicts += 1
        out.append(good[-1])
    print(f"    {ticker}: raw={len(raw)} unique={len(out)} conflict_dates={conflicts}")
    return out

def upsert(base_url, key, rows):
    url=f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json",
             "Prefer":"resolution=merge-duplicates,return=minimal"}
    total=math.ceil(len(rows)/DB_BATCH)
    for i,batch in enumerate(chunks(rows,DB_BATCH),1):
        r=requests.post(url,params={"on_conflict":"ticker,trade_date"},headers=headers,json=batch,timeout=120)
        print(f"  Supabase batch {i}/{total}: HTTP {r.status_code} ({len(batch)} rows)")
        if not r.ok:
            print(r.text[:2000]); r.raise_for_status()

def verify(base_url, key, tickers):
    counts=get_existing_counts(base_url,key,tickers)
    good=[(t,int(counts.get(t,0))) for t in tickers if counts.get(t,0)>=MIN_VALID_DAYS]
    bad=[(t,int(counts.get(t,0))) for t in tickers if counts.get(t,0)<MIN_VALID_DAYS]
    print("\n========== Supabase 验证 ==========")
    print(f"有足够一年原始日K(>={MIN_VALID_DAYS}日): {len(good)} / {len(tickers)}")
    if bad:
        print(f"⚠️ 数据不足/异常股票: {len(bad)}")
        for x in bad[:100]: print(" ",x)
        if len(bad)>100: print(f"  ...另有 {len(bad)-100} 只")
    return good,bad

def main():
    print("="*76)
    print("CMS Data Engine — A6 FINAL MISSING-ONLY RAW REPAIR")
    print("只补 <200 raw rows 的 ticker；不会重拉已完整股票")
    print(f"历史: {PERIOD} | Source: Business Quant")
    print("="*76)

    bq_key=env("BUSINESSQUANT_API_KEY")
    sb_url=env("SUPABASE_URL")
    sb_key=env("SUPABASE_SERVICE_ROLE_KEY")
    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL 必须是项目基础 URL，不能包含 /rest/v1")

    tickers=build_universe()

    print("\n🔎 先检查 Supabase 已有数据...")
    counts=get_existing_counts(sb_url,sb_key,tickers)
    already_good=[t for t in tickers if counts.get(t,0)>=MIN_VALID_DAYS]
    need_load=[t for t in tickers if counts.get(t,0)<MIN_VALID_DAYS]

    print("\n========== 初始化范围 ==========")
    print(f"目标股票池: {len(tickers)}")
    print(f"已有 >={MIN_VALID_DAYS} 日: {len(already_good)}")
    print(f"本次需要补齐: {len(need_load)}")

    if not need_load:
        print("✅ 所有股票已有足够原始日K，不需要重复下载。")
        return

    all_rows=[]; missing=[]
    batches=list(chunks(need_load,REQUEST_BATCH))
    for n,batch in enumerate(batches,1):
        print(f"\n📥 BQ 请求 {n}/{len(batches)}: {', '.join(batch)}")
        try:
            result=fetch_batch(bq_key,batch)
        except Exception as e:
            print(f"❌ 本批请求最终失败: {e}")
            missing.extend(batch)
            continue

        if isinstance(result,dict) and "metadata" in result and "data" in result:
            t=result.get("metadata",{}).get("ticker",batch[0])
            result={t:result}

        batch_rows=[]
        for t in batch:
            block=result.get(t) if isinstance(result,dict) else None
            rows=clean(t,block)
            if not rows:
                print(f"    ⚠️ {t} 无有效数据")
                missing.append(t)
            else:
                batch_rows.extend(rows)

        # 每成功一批立即写入，后续若遇到限额，本轮进度也不会丢。
        if batch_rows:
            print(f"📤 立即写入本批 {len(batch_rows)} rows 到 Supabase...")
            upsert(sb_url,sb_key,batch_rows)
            all_rows.extend(batch_rows)

    keys=[(r["ticker"],r["trade_date"]) for r in all_rows]
    if len(keys)!=len(set(keys)):
        fail("清洗后仍存在 ticker + trade_date 重复")

    print(f"\n📊 清洗完成: {len(all_rows)} 条唯一日K；有数据股票 {len(set(r['ticker'] for r in all_rows))}/{len(need_load)}")
    if missing:
        print("⚠️ 本轮无数据/请求失败:", ", ".join(sorted(set(missing))))
    if not all_rows:
        print("⚠️ 本轮没有新增 rows；继续执行最终验证。")

    good,bad=verify(sb_url,sb_key,tickers)

    print("\n"+"="*76)
    if len(good)==len(tickers):
        print(f"🎉 {len(good)}/{len(tickers)} 股票原始一年日K验证成功")
    else:
        print(f"⚠️ 本轮完成，但仅 {len(good)}/{len(tickers)} 达到 >={MIN_VALID_DAYS} 个交易日。")
        print("再次运行时只会继续补 <200 行的 ticker，不会重复下载已有完整数据。")
    print("")
    print("⚠️ 下一步运行 adjust_stock_daily_529.py，")
    print("为新增股票生成 adj_open/adj_high/adj_low/adj_close。")
    print("A6 FINAL 只有在 adj_* 齐全后才会把这些股票计为“可扫描”。")
    print("="*76)

if __name__ == "__main__":
    main()
