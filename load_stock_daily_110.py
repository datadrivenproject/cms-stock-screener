import os
import sys
import math
import time
import requests
from collections import defaultdict

BQ_URL = "https://data.businessquant.com/quotes"
TICKERS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX', 'ORCL', 'IBM', 'DELL', 'HPE', 'SMCI', 'CRM', 'ADBE', 'NOW', 'PLTR', 'PATH', 'CRWD', 'PANW', 'FTNT', 'DDOG', 'NET', 'SNOW', 'MDB', 'ZS', 'OKTA', 'TEAM', 'QCOM', 'MU', 'INTC', 'ARM', 'MRVL', 'AMAT', 'LRCX', 'KLAC', 'ON', 'MCHP', 'JPM', 'BAC', 'WFC', 'GS', 'MS', 'V', 'MA', 'AXP', 'PYPL', 'COIN', 'HOOD', 'SOFI', 'XYZ', 'NU', 'IBKR', 'LLY', 'UNH', 'ABBV', 'MRK', 'AMGN', 'JNJ', 'PFE', 'GILD', 'ISRG', 'TMO', 'TEM', 'VEEV', 'REGN', 'VRTX', 'DXCM', 'XOM', 'CVX', 'COP', 'CAT', 'GE', 'BA', 'RTX', 'LMT', 'ETN', 'VRT', 'PLUG', 'FCX', 'SLB', 'FSLR', 'CEG', 'WMT', 'COST', 'HD', 'DIS', 'UBER', 'ABNB', 'DASH', 'BKNG', 'SHOP', 'MELI', 'RBLX', 'SPOT', 'ROKU', 'DUOL', 'RDDT', 'CRCL', 'APP', 'RKLB', 'ASTS', 'IONQ', 'RGTI', 'SOUN', 'HIMS', 'CAVA', 'CVNA']
PERIOD = "1y"
REQUEST_BATCH = 10
DB_BATCH = 500
MAX_RETRIES = 3


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
    if v is None or v == "":
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def inum(v):
    if v is None or v == "":
        return None
    return int(float(v))


def valid(row):
    vals = [row[k] for k in ("open","high","low","close","volume")]
    if any(v is None for v in vals):
        return False
    o,h,l,c,v = vals
    return min(o,h,l,c) > 0 and v >= 0 and h >= max(o,l,c) and l <= min(o,h,c)


def fetch_batch(api_key, batch):
    params = {
        "ticker": ",".join(batch),
        "mode": "eod",
        "period": PERIOD,
        "limit": 500,
        "page": 1,
        "api_key": api_key,
    }
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(BQ_URL, params=params, timeout=120)
            print(f"  Business Quant HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            print(f"  ⚠️ 第 {attempt} 次请求失败: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
    raise last


def clean(ticker, block):
    raw = block.get("data", []) if isinstance(block, dict) else []
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
        normalized = []
        for x in grouped[d]:
            try:
                normalized.append({
                    "ticker": ticker,
                    "trade_date": d,
                    "open": fnum(x.get("open")),
                    "high": fnum(x.get("high")),
                    "low": fnum(x.get("low")),
                    "close": fnum(x.get("close")),
                    "volume": inum(x.get("volume")),
                    "source": "businessquant",
                })
            except Exception:
                continue

        good = [x for x in normalized if valid(x)]
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
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    for i, batch in enumerate(chunks(rows, DB_BATCH), start=1):
        r = requests.post(
            url,
            params={"on_conflict":"ticker,trade_date"},
            headers=headers,
            json=batch,
            timeout=120,
        )
        print(f"  Supabase batch {i}: HTTP {r.status_code} ({len(batch)} rows)")
        if not r.ok:
            print(r.text[:2000])
            r.raise_for_status()


def verify(base_url, key):
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Prefer": "count=exact",
        "Range": "0-0",
    }

    good, bad = [], []
    for t in TICKERS:
        r = requests.get(
            url,
            params={"select":"ticker","ticker":f"eq.{t}"},
            headers=headers,
            timeout=60,
        )
        if not r.ok:
            bad.append((t, f"HTTP {r.status_code}"))
            continue
        cr = r.headers.get("Content-Range","")
        try:
            count = int(cr.split("/")[-1])
        except Exception:
            count = 0
        (good if count >= 200 else bad).append((t, count))

    print("\n========== Supabase 验证 ==========")
    print(f"有足够一年数据(>=200日): {len(good)} / {len(TICKERS)}")
    if bad:
        print("⚠️ 数据不足/异常:")
        for x in bad:
            print(" ", x)
    return good, bad


def main():
    print("="*72)
    print("CMS Data Engine V2 - 原 A FINAL 110 股票池验证")
    print(f"股票数: {len(TICKERS)} | 历史: {PERIOD} | Source: Business Quant")
    print("="*72)

    bq_key = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL 必须是项目基础 URL，不能包含 /rest/v1")

    all_rows = []
    missing = []

    batches = list(chunks(TICKERS, REQUEST_BATCH))
    for n, batch in enumerate(batches, 1):
        print(f"\n📥 BQ 请求 {n}/{len(batches)}: {', '.join(batch)}")
        try:
            result = fetch_batch(bq_key, batch)
        except Exception as e:
            print(f"❌ 本批请求最终失败: {e}")
            missing.extend(batch)
            continue

        # Single-ticker compatible shape.
        if isinstance(result, dict) and "metadata" in result and "data" in result:
            t = result.get("metadata", {}).get("ticker", batch[0])
            result = {t: result}

        for t in batch:
            block = result.get(t) if isinstance(result, dict) else None
            rows = clean(t, block)
            if not rows:
                print(f"    ⚠️ {t} 无有效数据")
                missing.append(t)
            else:
                all_rows.extend(rows)

    keys = [(r["ticker"], r["trade_date"]) for r in all_rows]
    if len(keys) != len(set(keys)):
        fail("清洗后仍存在 ticker + trade_date 重复")

    print(f"\n📊 清洗完成: {len(all_rows)} 条唯一日K；有数据股票 {len(set(r['ticker'] for r in all_rows))}/{len(TICKERS)}")
    if missing:
        print("⚠️ 本轮无数据/请求失败:", ", ".join(sorted(set(missing))))

    if not all_rows:
        fail("没有可写入数据")

    print("\n📤 写入 Supabase stock_daily...")
    upsert(sb_url, sb_key, all_rows)

    good, bad = verify(sb_url, sb_key)

    print("\n" + "="*72)
    if len(good) == len(TICKERS):
        print("🎉 110/110 股票一年日K验证成功")
    else:
        print(f"⚠️ 本轮完成，但仅 {len(good)}/110 达到 >=200 个交易日。")
        print("这不会删除已有数据；下一步可只补失败股票。")
    print("="*72)


if __name__ == "__main__":
    main()
