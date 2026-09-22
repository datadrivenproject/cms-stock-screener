#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS ADJUSTED OHLC MAINTENANCE — SUPABASE ONLY

HARD RULES
----------
1) This file MUST NEVER call BusinessQuant or any external market-data API.
2) It reads raw OHLCV only from Supabase public.stock_daily.
3) Existing adj_open / adj_high / adj_low / adj_close values are preserved.
4) Only rows with missing adjusted values are filled.
5) For a ticker with prior adjusted history, the most recent known
   adjustment factor (adj_close / close) is carried forward to newer raw rows.
6) If a ticker has no prior adjusted history at all, factor 1.0 is used for
   raw rows so the series remains usable; this is reported clearly in logs.

This script is intentionally compatible with the production safety guard.
"""

import math
import os
import sys
from collections import defaultdict\nfrom datetime import date, timedelta

import requests


TABLE = "stock_daily"
READ_PAGE = 1000
WRITE_BATCH = 500
TICKER_BATCH = 25

ADJ_COLS = ["adj_open", "adj_high", "adj_low", "adj_close"]
RAW_COLS = ["open", "high", "low", "close"]


def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def env(name):
    value = os.getenv(name, "").strip()
    if not value:
        fail(f"缺少 GitHub Secret: {name}")
    return value


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def sb_headers(key):
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def get_base_url():
    base = env("SUPABASE_URL").rstrip("/")
    if "/rest/v1" in base:
        fail("SUPABASE_URL 必须是项目基础 URL，不能包含 /rest/v1")
    return base


def table_url(base):
    return f"{base}/rest/v1/{TABLE}"


def get_schema_columns(base, key):
    """Read one row to discover the real production table columns."""
    r = requests.get(
        table_url(base),
        params={"select": "*", "limit": 1},
        headers=sb_headers(key),
        timeout=60,
    )
    if not r.ok:
        print(r.text[:1500])
        r.raise_for_status()
    rows = r.json()
    if not rows:
        fail("stock_daily 为空，无法确认字段结构")
    return set(rows[0].keys())


def read_missing_adjusted_rows(base, key):
    """Read recent rows in small date-scoped pages, then filter missing adj_* locally.

    Avoids the expensive table-wide PostgREST OR-null scan that can hit the
    Supabase statement timeout. Daily maintenance only needs recent rows.
    """
    cols = "ticker,trade_date,open,high,low,close,adj_open,adj_high,adj_low,adj_close"
    rows = []
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    start = 0
    while True:
        headers = dict(sb_headers(key))
        headers["Range"] = f"{start}-{start + READ_PAGE - 1}"
        r = requests.get(
            table_url(base),
            params={
                "select": cols,
                "trade_date": f"gte.{cutoff}",
                "order": "trade_date.asc,ticker.asc",
            },
            headers=headers,
            timeout=120,
        )
        if not r.ok:
            print(r.text[:1500]); r.raise_for_status()
        page = r.json()
        rows.extend(
            row for row in page
            if any(fnum(row.get(col)) is None for col in ADJ_COLS)
        )
        if len(page) < READ_PAGE:
            break
        start += READ_PAGE
    return rows


def read_latest_factor(base, key, ticker):
    """Fetch one latest usable adjusted row for an affected ticker only."""
    r = requests.get(
        table_url(base),
        params={
            "select": "trade_date,close,adj_close",
            "ticker": f"eq.{ticker}",
            "close": "gt.0",
            "adj_close": "gt.0",
            "order": "trade_date.desc",
            "limit": 1,
        },
        headers=sb_headers(key),
        timeout=60,
    )
    if not r.ok:
        print(r.text[:1500]); r.raise_for_status()
    page = r.json()
    if not page: return 1.0, None
    row = page[0]
    close = fnum(row.get("close")); adj_close = fnum(row.get("adj_close"))
    if close and adj_close:
        factor = adj_close / close
        if math.isfinite(factor) and factor > 0:
            return factor, str(row.get("trade_date", ""))
    return 1.0, None


def fnum(v):
    try:
        if v is None or v == "":
            return None
        x = float(v)
        if math.isfinite(x):
            return x
    except Exception:
        pass
    return None


def has_all_adjusted(row):
    return all(fnum(row.get(c)) is not None for c in ADJ_COLS)


def raw_valid(row):
    vals = [fnum(row.get(c)) for c in RAW_COLS]
    return all(v is not None and v > 0 for v in vals)


def build_missing_adjusted_rows(ticker, rows, factor, factor_date):
    """Create payload from the already server-filtered missing rows."""
    updates = []
    for row in rows:
        if has_all_adjusted(row) or not raw_valid(row):
            continue
        out = {"ticker": ticker, "trade_date": row.get("trade_date")}
        for raw_col, adj_col in zip(RAW_COLS, ADJ_COLS):
            out[adj_col] = fnum(row.get(raw_col)) * factor
        updates.append(out)
    deduped = {}
    for item in updates:
        deduped[(item["ticker"], item["trade_date"])] = item
    return list(deduped.values())


def upsert_adjusted(base, key, rows):
    if not rows:
        return 0

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    total = 0
    for batch in chunks(rows, WRITE_BATCH):
        r = requests.post(
            table_url(base),
            params={"on_conflict": "ticker,trade_date"},
            headers=headers,
            json=batch,
            timeout=120,
        )
        if not r.ok:
            print(r.text[:2000])
            r.raise_for_status()
        total += len(batch)
    return total


def verify_missing(base, key):
    """Server-side verification: fetch only rows still missing adjusted values."""
    return read_missing_adjusted_rows(base, key)


def main():
    print("=" * 88)
    print("CMS ADJUSTED OHLC MAINTENANCE — SUPABASE ONLY")
    print("BusinessQuant access: FORBIDDEN")
    print("Historical external fetch: FORBIDDEN")
    print("=" * 88)

    base = get_base_url()
    key = env("SUPABASE_SERVICE_ROLE_KEY")

    cols = get_schema_columns(base, key)
    required = {"ticker", "trade_date", *RAW_COLS, *ADJ_COLS}
    missing_cols = sorted(required - cols)
    if missing_cols:
        fail("stock_daily 缺少必要字段: " + ", ".join(missing_cols))

    missing_rows = read_missing_adjusted_rows(base, key)
    if not missing_rows:
        print("No missing adjusted rows — fast exit.")
        print("✅ Supabase adjusted OHLC maintenance complete")
        print("✅ 0 BusinessQuant requests")
        print("✅ 0 historical external-data requests")
        return

    grouped = defaultdict(list)
    for row in missing_rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        if ticker:
            grouped[ticker].append(row)

    tickers = sorted(grouped)
    print(f"Missing adjusted rows: {len(missing_rows)} across {len(tickers)} affected tickers")
    print("FAST MODE: only affected tickers are processed; full-history scan is skipped.")

    total_updates = 0
    no_prior_adjustment = []
    for i, ticker in enumerate(tickers, 1):
        factor, factor_date = read_latest_factor(base, key, ticker)
        updates = build_missing_adjusted_rows(ticker, grouped[ticker], factor, factor_date)
        if factor_date is None and updates:
            no_prior_adjustment.append(ticker)
        written = upsert_adjusted(base, key, updates)
        total_updates += written
        src = factor_date if factor_date else "无历史factor→1.0"
        print(f"[{i:03d}/{len(tickers)}] {ticker}: 补 {written} rows | factor={factor:.8f} | source={src}")

    print("\n========== ADJUSTED MAINTENANCE SUMMARY ==========")
    print(f"写入/补齐 adjusted rows: {total_updates}")
    if no_prior_adjustment:
        print("⚠️ 无既有 adjusted history、因此使用 factor=1.0 的 ticker: " + ", ".join(no_prior_adjustment[:80]))

    remaining = [r for r in verify_missing(base, key) if raw_valid(r)]
    if remaining:
        counts = defaultdict(int)
        for row in remaining: counts[str(row.get("ticker",""))] += 1
        sample = ", ".join(f"{t}:{n}" for t,n in list(counts.items())[:50])
        fail("仍有 raw 有效但 adj_* 缺失的 rows: " + sample)

    print("✅ Supabase adjusted OHLC maintenance complete")
    print("✅ 0 BusinessQuant requests")
    print("✅ 0 historical external-data requests")


if __name__ == "__main__":
    main()
