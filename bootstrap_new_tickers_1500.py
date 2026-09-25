#!/usr/bin/env python3
"""Manual one-time bootstrap for NEW tickers only.

Daily production never calls this file. It finds current-universe tickers with
no Supabase history and seeds only those names with an explicit 365-day range.
Unsupported tickers are skipped without blocking the rest.
"""
import time
from datetime import datetime, timedelta
import requests

from universe_2500 import build_universe
from load_stock_daily import (
    BQ_URL, chunks, clean, env, fail, get_existing_status,
    normalize_multi_ticker_result, upsert, today_iso,
)

REQUEST_BATCH = 100
REQUEST_PAUSE_SECONDS = 10.0
MAX_429_RETRIES = 4
BACKOFF_429_SECONDS = [30, 60, 120, 180]

def fetch_history(api_key, batch, start, end):
    params = {
        "ticker": ",".join(batch),
        "mode": "daily",
        "from_date": start,
        "till_date": end,
        "limit": 500,
        "page": 1,
        "api_key": api_key,
    }
    for attempt in range(MAX_429_RETRIES + 1):
        r = requests.get(BQ_URL, params=params, timeout=180)
        print(f"BQ HTTP {r.status_code} | {start}->{end} | {len(batch)} tickers")
        if r.status_code != 429:
            r.raise_for_status()
            return normalize_multi_ticker_result(r.json(), batch)
        if attempt >= MAX_429_RETRIES:
            raise RuntimeError(f"BQ 429 persisted after {MAX_429_RETRIES} retries")
        wait_s = BACKOFF_429_SECONDS[attempt]
        retry_after = r.headers.get("Retry-After")
        try:
            if retry_after:
                wait_s = max(wait_s, int(float(retry_after)))
        except Exception:
            pass
        print(f"429 rate limit: wait {wait_s}s, then retry SAME batch ({attempt + 1}/{MAX_429_RETRIES})")
        time.sleep(wait_s)
    raise RuntimeError("BQ history request failed")

def main():
    print("=" * 78)
    print("CMS MANUAL BOOTSTRAP — NEW TICKERS ONLY")
    print("Daily production is unchanged; this script is manual only.")
    print("=" * 78)

    bq = env("BUSINESSQUANT_API_KEY")
    sb = env("SUPABASE_URL")
    key = env("SUPABASE_SERVICE_ROLE_KEY")
    if "/rest/v1" in sb:
        fail("SUPABASE_URL must be project base URL without /rest/v1")

    tickers = build_universe(verbose=True)
    _, latest = get_existing_status(sb, key, tickers)
    new_tickers = [t for t in tickers if not latest.get(t)]

    end = today_iso()
    start = (datetime.strptime(end, "%Y-%m-%d").date() - timedelta(days=365)).isoformat()
    print(f"Current universe: {len(tickers)}")
    print(f"Candidates absent from recent-status lookup: {len(new_tickers)}")
    print(f"Bootstrap window: {start} -> {end}")

    # Confirm exact absence before any historical request.
    url = f"{sb.rstrip('/')}/rest/v1/stock_daily"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    truly_new = []
    for t in new_tickers:
        r = requests.get(url, params={"select":"trade_date","ticker":f"eq.{t}","order":"trade_date.desc","limit":1},
                         headers=headers, timeout=30)
        r.raise_for_status()
        if not r.json():
            truly_new.append(t)

    print(f"Truly new/no-history tickers: {len(truly_new)}")
    if not truly_new:
        print("Nothing to bootstrap.")
        return

    for batch in chunks(truly_new, REQUEST_BATCH):
        try:
            result = fetch_history(bq, batch, start, end)
        except Exception as e:
            print(f"SKIP batch after controlled retries: {e}")
            print("Tickers:", ", ".join(batch))
            continue

        rows = []
        for t in batch:
            rows.extend(clean(t, result.get(t)))
        if rows:
            upsert(sb, key, rows)
        time.sleep(REQUEST_PAUSE_SECONDS)

    print("Bootstrap finished. Daily updater remains incremental-only.")

if __name__ == "__main__":
    main()
