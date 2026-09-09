#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS DATA ENGINE — 122 SYMBOL DAILY INCREMENTAL UPDATE v1.0

Purpose
-------
Update the existing Supabase public.stock_daily table for the frozen A5.2R
production universe:
  - 110 stocks
  - 12 benchmark/sector ETFs

Design
------
- Business Quant /quotes
- mode=eod (settled EOD only; never inject live bar)
- period=1mo (small rolling window instead of re-downloading 1 year)
- 10 tickers/request => 13 API calls for 122 symbols
- de-duplicate conflicting same-date rows exactly as the original loader did
- UPSERT raw OHLCV only
- DOES NOT overwrite adj_open/adj_high/adj_low/adj_close/adj_factor
- the existing 122 adjustment job remains responsible for adjusted fields

Required GitHub repository secrets
----------------------------------
BUSINESSQUANT_API_KEY
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
import math
import time
import requests
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

BQ_URL = "https://data.businessquant.com/quotes"

STOCKS_110 = [
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
    "SPY","XLK","XLV","XLF","XLY","XLP","XLI","XLE","XLB","XLU","XLRE","XLC"
]

TICKERS = STOCKS_110 + BENCHMARKS_12

# Business Quant supports multi-ticker requests.
# 122 / 10 = 13 calls per normal run, comfortably below the account's
# previously observed 40-request/day limit.
REQUEST_BATCH = 10
PERIOD = "1mo"
BQ_LIMIT = 100
DB_BATCH = 500
MAX_RETRIES = 2
NY = ZoneInfo("America/New_York")


def fail(msg):
    print(f"❌ {msg}", flush=True)
    sys.exit(1)


def env(name):
    value = os.getenv(name, "").strip()
    if not value:
        fail(f"Missing GitHub Secret: {name}")
    return value


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
    vals = [row[k] for k in ("open", "high", "low", "close", "volume")]
    if any(v is None for v in vals):
        return False
    o, h, l, c, v = vals
    return (
        min(o, h, l, c) > 0
        and v >= 0
        and h >= max(o, l, c)
        and l <= min(o, h, c)
    )


def fetch_batch(api_key, batch):
    params = {
        "ticker": ",".join(batch),
        "mode": "eod",
        "period": PERIOD,
        "limit": BQ_LIMIT,
        "page": 1,
        "api_key": api_key,
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(BQ_URL, params=params, timeout=120)
            print(f"  Business Quant HTTP {r.status_code}", flush=True)

            # Give a clearer message for daily quota exhaustion.
            if r.status_code == 429:
                raise RuntimeError(f"Business Quant rate limit: {r.text[:500]}")

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_error = e
            print(f"  ⚠️ attempt {attempt}/{MAX_RETRIES} failed: {e}", flush=True)
            if attempt < MAX_RETRIES:
                time.sleep(4 * attempt)

    raise last_error


def normalize_multi_ticker_response(result, batch):
    """
    Business Quant:
    - single ticker may return {"metadata":..., "data":[...]}
    - multi ticker returns { "AAPL": {...}, "MSFT": {...}, ... }
    """
    if isinstance(result, dict) and "metadata" in result and "data" in result:
        ticker = str(result.get("metadata", {}).get("ticker", batch[0])).upper()
        return {ticker: result}
    return result if isinstance(result, dict) else {}


def clean_ticker(ticker, block):
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
        normalized = []
        for x in grouped[d]:
            try:
                row = {
                    "ticker": ticker,
                    "trade_date": d,
                    "open": fnum(x.get("open")),
                    "high": fnum(x.get("high")),
                    "low": fnum(x.get("low")),
                    "close": fnum(x.get("close")),
                    "volume": inum(x.get("volume")),
                    "source": "businessquant",
                }
            except Exception:
                continue

            if valid(row):
                normalized.append(row)

        if not normalized:
            continue

        if len(normalized) > 1:
            sig = {
                (x["open"], x["high"], x["low"], x["close"], x["volume"])
                for x in normalized
            }
            if len(sig) > 1:
                conflicts += 1

        # Match the previously validated loader: keep the API-returned last
        # valid record for a duplicate trade date.
        out.append(normalized[-1])

    if out:
        print(
            f"    {ticker}: rows={len(out)} "
            f"latest={out[-1]['trade_date']} "
            f"duplicate_conflict_dates={conflicts}",
            flush=True
        )
    return out


def upsert_supabase(base_url, service_key, rows):
    """
    Only raw columns are sent. Existing adjusted columns are intentionally
    omitted so this job does not replace them. Newly inserted trade dates will
    have adjusted fields populated by adjust_stock_daily_122.py afterwards.
    """
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    for i, batch in enumerate(chunks(rows, DB_BATCH), 1):
        r = requests.post(
            url,
            params={"on_conflict": "ticker,trade_date"},
            headers=headers,
            json=batch,
            timeout=120,
        )
        print(
            f"  Supabase batch {i}: HTTP {r.status_code} ({len(batch)} rows)",
            flush=True
        )
        if not r.ok:
            print(r.text[:2000], flush=True)
            r.raise_for_status()


def main():
    if len(STOCKS_110) != 110:
        fail(f"Internal universe error: expected 110 stocks, found {len(STOCKS_110)}")
    if len(BENCHMARKS_12) != 12:
        fail(f"Internal universe error: expected 12 benchmarks, found {len(BENCHMARKS_12)}")
    if len(TICKERS) != 122 or len(set(TICKERS)) != 122:
        fail("Internal universe error: 122-symbol list is not unique")

    bq_key = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL must be project base URL, without /rest/v1")

    now = datetime.now(NY)

    print("=" * 84, flush=True)
    print("CMS 122 DAILY INCREMENTAL UPDATE v1.0", flush=True)
    print(f"Run time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}", flush=True)
    print(f"Universe: 110 stocks + 12 benchmarks = {len(TICKERS)}", flush=True)
    print(
        f"Business Quant: mode=eod | period={PERIOD} | "
        f"batch={REQUEST_BATCH} | planned calls={math.ceil(len(TICKERS)/REQUEST_BATCH)}",
        flush=True
    )
    print("=" * 84, flush=True)

    all_rows = []
    failed_tickers = []

    batches = list(chunks(TICKERS, REQUEST_BATCH))

    for n, batch in enumerate(batches, 1):
        print(
            f"\n📥 BQ request {n}/{len(batches)}: {', '.join(batch)}",
            flush=True
        )

        try:
            result = fetch_batch(bq_key, batch)
        except Exception as e:
            print(f"❌ Batch failed: {e}", flush=True)
            failed_tickers.extend(batch)
            continue

        result = normalize_multi_ticker_response(result, batch)

        for ticker in batch:
            block = result.get(ticker)
            rows = clean_ticker(ticker, block)
            if not rows:
                print(f"    ⚠️ {ticker}: no valid EOD rows", flush=True)
                failed_tickers.append(ticker)
            else:
                all_rows.extend(rows)

    # Strong local integrity check before touching Supabase.
    keys = [(r["ticker"], r["trade_date"]) for r in all_rows]
    if len(keys) != len(set(keys)):
        fail("Cleaned payload still contains duplicate ticker + trade_date keys")

    covered = sorted(set(r["ticker"] for r in all_rows))
    print("\n" + "=" * 84, flush=True)
    print(
        f"Fetched valid data for {len(covered)}/122 symbols; "
        f"{len(all_rows)} rolling-window rows",
        flush=True
    )

    if failed_tickers:
        uniq_fail = sorted(set(failed_tickers))
        print("⚠️ Missing/failed symbols:", ", ".join(uniq_fail), flush=True)

    # A normal production update should never silently write a partial universe.
    # This protects A from a half-updated market/benchmark dataset.
    if len(covered) != 122:
        fail(
            f"Partial update blocked: only {len(covered)}/122 symbols returned valid data. "
            "Supabase was NOT changed."
        )

    print("\n📤 Upserting raw rolling EOD window to Supabase...", flush=True)
    upsert_supabase(sb_url, sb_key, all_rows)

    latest_by_ticker = {}
    for r in all_rows:
        latest_by_ticker[r["ticker"]] = max(
            r["trade_date"],
            latest_by_ticker.get(r["ticker"], "")
        )

    latest_dates = sorted(set(latest_by_ticker.values()))
    print("\nLatest fetched trade dates:", ", ".join(latest_dates), flush=True)

    if len(latest_dates) > 1:
        print(
            "ℹ️ Different latest dates can occur for a recently halted/listed security; "
            "review if unexpected.",
            flush=True
        )

    print("\n✅ 122/122 raw EOD update completed.", flush=True)
    print(
        "✅ Adjusted fields were not overwritten. "
        "Next step: run Adjust 122 A5 Symbols.",
        flush=True
    )


if __name__ == "__main__":
    main()
