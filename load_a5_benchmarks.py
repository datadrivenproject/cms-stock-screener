import os
import sys
import math
import requests
from collections import defaultdict

BQ_URL = "https://data.businessquant.com/quotes"
TICKERS = ['SPY', 'XLK', 'XLV', 'XLF', 'XLY', 'XLP', 'XLI', 'XLE', 'XLB', 'XLU', 'XLRE', 'XLC']
PERIOD = "1y"


def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def env(name):
    v = os.getenv(name, "").strip()
    if not v:
        fail(f"缺少 GitHub Secret: {name}")
    return v


def fnum(v):
    if v is None or v == "":
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def inum(v):
    if v is None or v == "":
        return None
    return int(float(v))


def valid(r):
    vals = [r[k] for k in ("open","high","low","close","volume")]
    if any(v is None for v in vals):
        return False
    o,h,l,c,v = vals
    return min(o,h,l,c) > 0 and v >= 0 and h >= max(o,l,c) and l <= min(o,h,c)


def main():
    bq_key = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL").rstrip("/")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    params = {
        "ticker": ",".join(TICKERS),
        "mode": "eod",
        "period": PERIOD,
        "limit": 500,
        "page": 1,
        "api_key": bq_key,
    }

    print("📥 下载 A5.2R benchmark ETFs...")
    r = requests.get(BQ_URL, params=params, timeout=120)
    print("Business Quant HTTP:", r.status_code)
    r.raise_for_status()
    result = r.json()

    all_rows = []
    for t in TICKERS:
        block = result.get(t, {}) if isinstance(result, dict) else {}
        raw = block.get("data", [])
        grouped = defaultdict(list)
        for x in raw:
            d = str(x.get("date",""))[:10]
            if d:
                grouped[d].append(x)

        cleaned = []
        for d in sorted(grouped):
            candidates = []
            for x in grouped[d]:
                row = {
                    "ticker": t,
                    "trade_date": d,
                    "open": fnum(x.get("open")),
                    "high": fnum(x.get("high")),
                    "low": fnum(x.get("low")),
                    "close": fnum(x.get("close")),
                    "volume": inum(x.get("volume")),
                    "source": "businessquant",
                }
                if valid(row):
                    candidates.append(row)
            if candidates:
                cleaned.append(candidates[-1])

        print(f"{t}: {len(cleaned)} unique daily bars")
        if len(cleaned) < 200:
            fail(f"{t} 一年数据不足 200 个交易日")
        all_rows.extend(cleaned)

    url = f"{sb_url}/rest/v1/stock_daily"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    for i in range(0, len(all_rows), 500):
        batch = all_rows[i:i+500]
        r = requests.post(
            url,
            params={"on_conflict":"ticker,trade_date"},
            headers=headers,
            json=batch,
            timeout=120,
        )
        print(f"Supabase {i+1}-{i+len(batch)} HTTP:", r.status_code)
        if not r.ok:
            print(r.text[:2000])
            r.raise_for_status()

    print(f"🎉 Benchmark ETFs 写入完成: {len(TICKERS)}/12")


if __name__ == "__main__":
    main()
