#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS — Adjust 110 stocks using EXISTING Supabase raw OHLC
and ONE batched Business Quant corporate-actions request.

Why V2:
- Business Quant free plan is limited to 40 requests/day.
- We already have the 110 stocks' 1-year raw OHLC in Supabase.
- Therefore we DO NOT call Business Quant /quotes again.
- Corporate Actions API supports comma-separated tickers, so all 110 tickers
  are requested in one call.

Writes only:
  adj_open, adj_high, adj_low, adj_close, adj_factor

Raw open/high/low/close remain untouched.
"""

import os
import sys
from typing import Any, Dict, List
import numpy as np
import pandas as pd
import requests


UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","ORCL","IBM","DELL","HPE","SMCI",
    "CRM","ADBE","NOW","PLTR","PATH","CRWD","PANW","FTNT","DDOG","NET","SNOW","MDB","ZS","OKTA","TEAM",
    "QCOM","MU","INTC","ARM","MRVL","AMAT","LRCX","KLAC","ON","MCHP",
    "JPM","BAC","WFC","GS","MS","V","MA","AXP","PYPL","COIN","HOOD","SOFI","XYZ","NU","IBKR",
    "LLY","UNH","ABBV","MRK","AMGN","JNJ","PFE","GILD","ISRG","TMO","TEM","VEEV","REGN","VRTX","DXCM",
    "XOM","CVX","COP","CAT","GE","BA","RTX","LMT","ETN","VRT","PLUG","FCX","SLB","FSLR","CEG",
    "WMT","COST","HD","DIS","UBER","ABNB","DASH","BKNG","SHOP","MELI","RBLX","SPOT","ROKU","DUOL","RDDT",
    "CRCL","APP","RKLB","ASTS","IONQ","RGTI","SOUN","HIMS","CAVA","CVNA"
]

BQ_BASE = "https://data.businessquant.com"
SESSION = requests.Session()


def must_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        print(f"❌ Missing secret: {name}")
        sys.exit(2)
    return v


BQ_KEY = must_env("BUSINESSQUANT_API_KEY")
SUPABASE_URL = must_env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = must_env("SUPABASE_SERVICE_ROLE_KEY")


def sb_headers(count=False):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    if count:
        h["Prefer"] = "count=exact"
    return h


def fetch_all_raw_from_supabase() -> pd.DataFrame:
    """
    Read all existing raw OHLC rows for the 110-stock universe.
    Uses PostgREST pagination so the default 1000-row limit is not a problem.
    """
    url = f"{SUPABASE_URL}/rest/v1/stock_daily"
    ticker_filter = "in.(" + ",".join(UNIVERSE) + ")"

    rows = []
    start = 0
    page_size = 1000

    while True:
        headers = sb_headers()
        headers["Range"] = f"{start}-{start + page_size - 1}"
        params = {
            "select": "ticker,trade_date,open,high,low,close",
            "ticker": ticker_filter,
            "order": "ticker.asc,trade_date.asc",
        }
        r = SESSION.get(url, headers=headers, params=params, timeout=60)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"Supabase read HTTP {r.status_code}: {r.text[:500]}")

        batch = r.json()
        if not batch:
            break

        rows.extend(batch)
        print(f"Supabase raw read: +{len(batch)} rows | total={len(rows)}")

        if len(batch) < page_size:
            break
        start += page_size

    if not rows:
        raise RuntimeError("No stock_daily raw rows returned from Supabase.")

    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.normalize()
    for c in ["open","high","low","close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = (
        df.dropna(subset=["ticker","trade_date","close"])
          .drop_duplicates(["ticker","trade_date"], keep="last")
          .sort_values(["ticker","trade_date"])
          .reset_index(drop=True)
    )
    return df


def fetch_actions_one_request() -> pd.DataFrame:
    """
    One Business Quant request for all 110 tickers.
    Official Corporate Actions API accepts comma-separated tickers.
    """
    params = {
        "ticker": ",".join(UNIVERSE),
        "action": "dividend,split",
        "period": "1y",
        "limit": 10000,
        "page": 1,
        "api_key": BQ_KEY,
    }
    r = SESSION.get(f"{BQ_BASE}/corporate_actions", params=params, timeout=60)

    # If no actions at all, treat as empty (unlikely for 110 stocks).
    if r.status_code == 404:
        print("Business Quant corporate actions: HTTP 404 -> treat as 0 actions")
        return pd.DataFrame(columns=["date","ticker","action","value","notes"])

    if r.status_code != 200:
        safe_url = r.url.split("api_key=")[0] + "api_key=***"
        raise RuntimeError(
            f"Business Quant corporate-actions HTTP {r.status_code}: "
            f"{safe_url} | {r.text[:500]}"
        )

    payload = r.json()
    if isinstance(payload, dict):
        data = payload.get("data", [])
        # defensive fallback if response is keyed by ticker
        if not data:
            temp = []
            for k, v in payload.items():
                if isinstance(v, dict) and isinstance(v.get("data"), list):
                    temp.extend(v["data"])
            data = temp
    elif isinstance(payload, list):
        data = payload
    else:
        data = []

    if not data:
        print("Business Quant corporate actions: 0 rows")
        return pd.DataFrame(columns=["date","ticker","action","value","notes"])

    df = pd.DataFrame(data)
    for c in ["date","ticker","action","value","notes"]:
        if c not in df.columns:
            df[c] = np.nan

    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["action"] = df["action"].astype(str).str.lower().str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df = df[
        df["ticker"].isin(UNIVERSE)
        & df["action"].isin(["dividend","split"])
    ].dropna(subset=["date","ticker"]).sort_values(["ticker","date"])

    print(f"Business Quant corporate actions: {len(df)} rows in ONE API request")
    return df.reset_index(drop=True)


def adjust_one(raw: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    out = raw.copy().sort_values("trade_date").reset_index(drop=True)
    out["adj_factor"] = 1.0

    for _, a in actions.sort_values("date").iterrows():
        adate = a["date"]
        action = str(a["action"]).lower()
        value = a["value"]

        prior = out["trade_date"] < adate
        if not prior.any():
            continue

        event_factor = np.nan

        if action == "split":
            # Business Quant: value = new shares / old shares
            if pd.notna(value) and float(value) > 0:
                event_factor = 1.0 / float(value)

        elif action == "dividend":
            if pd.notna(value) and float(value) >= 0:
                prev = out.loc[prior, ["trade_date","close"]].dropna()
                if not prev.empty:
                    prev_close = float(prev.iloc[-1]["close"])
                    dividend = float(value)
                    if prev_close > 0 and dividend < prev_close:
                        event_factor = (prev_close - dividend) / prev_close

        if pd.notna(event_factor) and float(event_factor) > 0:
            out.loc[prior, "adj_factor"] *= float(event_factor)

    for c in ["open","high","low","close"]:
        out[f"adj_{c}"] = out[c] * out["adj_factor"]

    return out


def clean_float(x):
    if pd.isna(x):
        return None
    return float(x)


def upsert_adjusted(rows: List[dict], batch_size=500):
    url = f"{SUPABASE_URL}/rest/v1/stock_daily?on_conflict=ticker,trade_date"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        r = SESSION.post(url, headers=headers, json=batch, timeout=60)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(
                f"Supabase upsert HTTP {r.status_code}: {r.text[:500]}"
            )
        print(f"Supabase write batch {i//batch_size+1}: {len(batch)} rows | HTTP {r.status_code}")


def verify_counts() -> pd.DataFrame:
    url = f"{SUPABASE_URL}/rest/v1/stock_daily"
    result = []

    for t in UNIVERSE:
        headers = sb_headers(count=True)
        headers["Range"] = "0-0"
        params = {
            "select": "ticker",
            "ticker": f"eq.{t}",
            "adj_close": "not.is.null",
        }
        r = SESSION.get(url, headers=headers, params=params, timeout=30)
        if r.status_code not in (200,206):
            count = -1
        else:
            cr = r.headers.get("Content-Range","")
            try:
                count = int(cr.split("/")[-1])
            except Exception:
                count = -1
        result.append({"ticker": t, "adjusted_rows": count})

    return pd.DataFrame(result)


def main():
    print("="*90)
    print("CMS 110 STOCK ADJUSTMENT V2")
    print("Raw price source: EXISTING Supabase")
    print("Corporate actions: ONE batched Business Quant request")
    print("="*90)

    raw_all = fetch_all_raw_from_supabase()
    print(f"\nTotal raw rows loaded from Supabase: {len(raw_all)}")

    present = set(raw_all["ticker"].unique())
    missing = [t for t in UNIVERSE if t not in present]
    if missing:
        print("❌ Missing raw ticker(s) in Supabase:", ", ".join(missing))
        sys.exit(1)

    actions_all = fetch_actions_one_request()

    write_rows = []
    status = []

    for i, ticker in enumerate(UNIVERSE, 1):
        raw = raw_all[raw_all["ticker"] == ticker].copy()
        acts = actions_all[actions_all["ticker"] == ticker].copy()
        adj = adjust_one(raw, acts)

        for _, r in adj.iterrows():
            write_rows.append({
                "ticker": ticker,
                "trade_date": r["trade_date"].date().isoformat(),
                "adj_open": clean_float(r["adj_open"]),
                "adj_high": clean_float(r["adj_high"]),
                "adj_low": clean_float(r["adj_low"]),
                "adj_close": clean_float(r["adj_close"]),
                "adj_factor": clean_float(r["adj_factor"]),
            })

        status.append({
            "ticker": ticker,
            "raw_rows": len(raw),
            "corporate_actions": len(acts),
            "min_adj_factor": float(adj["adj_factor"].min()),
            "max_adj_factor": float(adj["adj_factor"].max()),
        })

        print(
            f"[{i:03d}/110] {ticker}: raw={len(raw)} "
            f"| actions={len(acts)} "
            f"| factor={adj['adj_factor'].min():.9f}–{adj['adj_factor'].max():.9f}"
        )

    print(f"\nPrepared {len(write_rows)} adjusted rows for Supabase.")
    upsert_adjusted(write_rows)

    status_df = pd.DataFrame(status)
    verify_df = verify_counts()
    final_df = status_df.merge(verify_df, on="ticker", how="left")
    final_df["status"] = np.where(final_df["adjusted_rows"] >= 200, "OK", "CHECK")
    final_df.to_csv("adjust_110_v2_status.csv", index=False, encoding="utf-8-sig")

    ok = int((final_df["status"] == "OK").sum())
    check = int((final_df["status"] != "OK").sum())

    print("\n" + "="*90)
    print("FINAL SUMMARY")
    print("="*90)
    print(f"OK (>=200 adjusted rows): {ok}/110")
    print(f"CHECK: {check}")
    if check:
        print(final_df[final_df["status"] != "OK"][["ticker","adjusted_rows"]].to_string(index=False))

    if ok != 110:
        sys.exit(1)

    print("\n✅ 110/110 adjusted OHLC successfully stored in Supabase.")
    print("✅ Original raw OHLC was preserved.")
    print("✅ A5.2R logic was not modified.")


if __name__ == "__main__":
    main()
