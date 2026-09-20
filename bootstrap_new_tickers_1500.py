#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ONE-TIME history bootstrap for new CMS universe members.

This program is deliberately separate from daily production. It loads one year
only for tickers that have fewer than MIN_VALID_DAYS in Supabase. The daily
updater remains true-incremental and never calls this program.
"""

import time

import requests

from universe_2500 import build_universe
from load_stock_daily_529 import (
    BQ_URL,
    MIN_VALID_DAYS,
    chunks,
    clean,
    env,
    fail,
    get_existing_status,
    normalize_multi_ticker_result,
    upsert,
    verify,
)


HISTORY_PERIOD = "1y"
REQUEST_BATCH = 100
MAX_TICKERS_PER_RUN = 200
AUTO_MAX_BATCHES = 5
REQUEST_PAUSE_SECONDS = 4.0
MAX_RETRIES = 3


def fetch_history_batch(api_key, batch):
    params = {
        "ticker": ",".join(batch),
        "mode": "eod",
        "period": HISTORY_PERIOD,
        "limit": 500,
        "page": 1,
        "api_key": api_key,
    }
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(BQ_URL, params=params, timeout=180)
            print(
                f"  Business Quant HTTP {response.status_code} | "
                f"history bootstrap | {len(batch)} tickers"
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            print(f"  WARNING: bootstrap attempt {attempt} failed: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(15 * attempt)
    raise last_error


def main():
    print("=" * 88)
    print("CMS ONE-TIME HISTORY BOOTSTRAP — EXPANDED 2500 UNIVERSE")
    print("Auto mode: up to 200 incomplete tickers per batch; repeats until complete.")
    print("=" * 88)

    bq_key = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")
    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL must be the project base URL, without /rest/v1")

    tickers = build_universe(verbose=True)

    for auto_batch in range(1, AUTO_MAX_BATCHES + 1):
        counts, _ = get_existing_status(sb_url, sb_key, tickers)
        complete = [t for t in tickers if counts.get(t, 0) >= MIN_VALID_DAYS]
        all_need_history = [t for t in tickers if counts.get(t, 0) < MIN_VALID_DAYS]
        need_history = all_need_history[:MAX_TICKERS_PER_RUN]

        print(f"\n========== AUTO BATCH {auto_batch}/{AUTO_MAX_BATCHES} ==========")
        print(f"Target universe: {len(tickers)}")
        print(f"Already complete (>={MIN_VALID_DAYS} days): {len(complete)}")
        print(f"Still needing history: {len(all_need_history)}")
        print(f"This batch: {len(need_history)}/{MAX_TICKERS_PER_RUN}")

        if not need_history:
            print("All universe tickers already have sufficient history. Nothing fetched.")
            break

        failed = []
        batches = list(chunks(need_history, REQUEST_BATCH))
        for batch_number, batch in enumerate(batches, 1):
            print(f"\nHistory request {batch_number}/{len(batches)} ({len(batch)} tickers): {', '.join(batch)}")
            try:
                result = fetch_history_batch(bq_key, batch)
            except Exception as exc:
                print(f"ERROR: history request failed: {exc}")
                failed.extend(batch)
                continue

            result = normalize_multi_ticker_result(result, batch)
            batch_rows = []
            for ticker in batch:
                rows = clean(ticker, result.get(ticker))
                if rows:
                    batch_rows.extend(rows)
                else:
                    failed.append(ticker)
                    print(f"    WARNING: {ticker}: no valid history returned")

            keys = [(row["ticker"], row["trade_date"]) for row in batch_rows]
            if len(keys) != len(set(keys)):
                fail("Duplicate ticker + trade_date generated during bootstrap")
            if batch_rows:
                print(f"Writing {len(batch_rows)} history rows for this request...")
                upsert(sb_url, sb_key, batch_rows)
            if batch_number < len(batches):
                time.sleep(REQUEST_PAUSE_SECONDS)

        if failed:
            print(f"No data/request failure in auto batch {auto_batch} ({len(set(failed))}):")
            print(", ".join(sorted(set(failed))))

        # Re-check Supabase before selecting the next 200. Completed names are never fetched again.
        final_counts, _, _ = verify(sb_url, sb_key, tickers)
        sufficient = sum(final_counts.get(t, 0) >= MIN_VALID_DAYS for t in tickers)
        print(f"After auto batch {auto_batch}: sufficient history {sufficient}/{len(tickers)}")
        if sufficient >= len(tickers):
            print("Expanded universe bootstrap complete.")
            break
        time.sleep(REQUEST_PAUSE_SECONDS)

    print("\nBootstrap auto-run finished. Daily updater remains true-incremental only.")


if __name__ == "__main__":
    main()
