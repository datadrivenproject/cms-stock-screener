#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS — Back-adjust Business Quant OHLC for the original 110-stock universe
and write adjusted fields back into Supabase stock_daily.

Writes:
  adj_open
  adj_high
  adj_low
  adj_close
  adj_factor

Rules:
- Keep original raw OHLC untouched.
- Business Quant corporate actions:
    split    -> backward factor *= 1 / ratio
    dividend -> backward factor *= (prev_close - dividend) / prev_close
- Corporate Actions HTTP 404 is treated as "no actions".
- Deduplicate EOD by trade date, keeping the last API-returned record.
- Upsert only adjusted fields for existing (ticker, trade_date) rows.
- A5.2R strategy logic is NOT changed by this script.
"""

import os
import sys
import math
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import requests


BQ_BASE = "https://data.businessquant.com"
TIMEOUT = 40

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


def must_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        print(f"❌ Missing environment secret: {name}")
        sys.exit(2)
    return v


BQ_KEY = must_env("BUSINESSQUANT_API_KEY")
SUPABASE_URL = must_env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = must_env("SUPABASE_SERVICE_ROLE_KEY")

SESSION = requests.Session()


def bq_get(path: str, params: Dict[str, Any], allow_404=False) -> Any:
    p = dict(params)
    p["api_key"] = BQ_KEY
    r = SESSION.get(f"{BQ_BASE}{path}", params=p, timeout=TIMEOUT)

    if allow_404 and r.status_code == 404:
        return None

    if r.status_code != 200:
        safe_url = r.url.split("api_key=")[0] + "api_key=***"
        raise RuntimeError(f"BQ HTTP {r.status_code}: {safe_url} | {r.text[:300]}")
    return r.json()


def extract_rows(payload: Any, ticker: str) -> List[dict]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    if ticker in payload and isinstance(payload[ticker], dict):
        return payload[ticker].get("data", []) or []

    if "data" in payload:
        return payload.get("data", []) or []

    for v in payload.values():
        if isinstance(v, dict) and "data" in v:
            return v.get("data", []) or []

    return []


def fetch_eod(ticker: str) -> pd.DataFrame:
    payload = bq_get(
        "/quotes",
        {
            "ticker": ticker,
            "mode": "eod",
            "period": "1y",
            "limit": 10000,
            "page": 1,
        }
    )
    rows = extract_rows(payload, ticker)
    if not rows:
        raise RuntimeError("No EOD rows")

    df = pd.DataFrame(rows)
    date_col = next((c for c in ["date","pricedate","trade_date"] if c in df.columns), None)
    if not date_col:
        raise RuntimeError(f"No date column: {list(df.columns)}")

    df = df.rename(columns={date_col: "trade_date"})
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if cl in {"open","high","low","close","volume"}:
            rename[c] = cl
    df = df.rename(columns=rename)

    need = ["trade_date","open","high","low","close"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing EOD fields: {missing}")

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for c in ["open","high","low","close","volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    before = len(df)
    df = (
        df.dropna(subset=["trade_date","close"])
          .drop_duplicates(subset=["trade_date"], keep="last")
          .sort_values("trade_date")
          .reset_index(drop=True)
    )
    if len(df) < before:
        print(f"    deduped {before-len(df)} EOD rows")
    return df


def fetch_actions(ticker: str) -> pd.DataFrame:
    payload = bq_get(
        "/corporate_actions",
        {
            "ticker": ticker,
            "action": "dividend,split",
            "period": "1y",
            "limit": 10000,
            "page": 1,
        },
        allow_404=True
    )
    if payload is None:
        return pd.DataFrame(columns=["date","action","value","notes"])

    rows = extract_rows(payload, ticker)
    if not rows:
        return pd.DataFrame(columns=["date","action","value","notes"])

    df = pd.DataFrame(rows)
    for c in ["date","action","value","notes"]:
        if c not in df.columns:
            df[c] = np.nan

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    df["action"] = df["action"].astype(str).str.lower().str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def make_adjusted(raw: pd.DataFrame, actions: pd.DataFrame) -> Tuple[pd.DataFrame, List[dict]]:
    out = raw.copy()
    out["adj_factor"] = 1.0
    applied = []

    for _, a in actions.iterrows():
        adate = a["date"]
        action = str(a["action"]).lower()
        value = a["value"]
        notes = "" if pd.isna(a.get("notes")) else str(a.get("notes"))

        prior_mask = out["trade_date"] < adate
        if not prior_mask.any():
            continue

        event_factor = np.nan

        if action == "split":
            if pd.notna(value) and float(value) > 0:
                event_factor = 1.0 / float(value)

        elif action == "dividend":
            if pd.notna(value) and float(value) >= 0:
                prev = out.loc[prior_mask, ["trade_date","close"]].dropna()
                if not prev.empty:
                    pprev = float(prev.iloc[-1]["close"])
                    d = float(value)
                    if pprev > 0 and d < pprev:
                        event_factor = (pprev - d) / pprev

        if pd.notna(event_factor) and event_factor > 0:
            out.loc[prior_mask, "adj_factor"] *= float(event_factor)
            applied.append({
                "date": adate.date().isoformat(),
                "action": action,
                "value": None if pd.isna(value) else float(value),
                "factor": float(event_factor),
                "notes": notes
            })

    for c in ["open","high","low","close"]:
        out[f"adj_{c}"] = out[c] * out["adj_factor"]

    return out, applied


def supabase_upsert(rows: List[dict], batch_size=500):
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/stock_daily?on_conflict=ticker,trade_date"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        r = SESSION.post(url, headers=headers, json=batch, timeout=60)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"Supabase upsert failed HTTP {r.status_code}: {r.text[:500]}")
        print(f"    Supabase batch {i//batch_size + 1}: {len(batch)} rows | HTTP {r.status_code}")


def supabase_count_adjusted(ticker: str) -> int:
    url = f"{SUPABASE_URL}/rest/v1/stock_daily"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Prefer": "count=exact"
    }
    params = {
        "select": "ticker",
        "ticker": f"eq.{ticker}",
        "adj_close": "not.is.null"
    }
    r = SESSION.get(url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        return -1
    cr = r.headers.get("Content-Range", "")
    try:
        return int(cr.split("/")[-1])
    except Exception:
        return len(r.json()) if isinstance(r.json(), list) else -1


def clean_num(x):
    if pd.isna(x):
        return None
    return float(x)


def main():
    all_status = []
    failed = []

    print(f"CMS 110-stock official adjustment writeback")
    print(f"Universe size: {len(UNIVERSE)}")
    print("Original OHLC will NOT be overwritten.\n")

    for idx, ticker in enumerate(UNIVERSE, start=1):
        print("="*72)
        print(f"[{idx:03d}/{len(UNIVERSE)}] {ticker}")
        try:
            raw = fetch_eod(ticker)
            actions = fetch_actions(ticker)
            adj, applied = make_adjusted(raw, actions)

            rows = []
            for _, r in adj.iterrows():
                rows.append({
                    "ticker": ticker,
                    "trade_date": r["trade_date"].date().isoformat(),
                    "adj_open": clean_num(r["adj_open"]),
                    "adj_high": clean_num(r["adj_high"]),
                    "adj_low": clean_num(r["adj_low"]),
                    "adj_close": clean_num(r["adj_close"]),
                    "adj_factor": clean_num(r["adj_factor"]),
                })

            supabase_upsert(rows)

            n_adj = supabase_count_adjusted(ticker)
            status = {
                "ticker": ticker,
                "eod_rows": len(raw),
                "corporate_actions": len(actions),
                "applied_actions": len(applied),
                "adjusted_rows_in_supabase": n_adj,
                "min_adj_factor": float(adj["adj_factor"].min()),
                "max_adj_factor": float(adj["adj_factor"].max()),
                "status": "OK" if n_adj >= 200 else "CHECK"
            }
            all_status.append(status)

            print(
                f"    EOD={len(raw)} | actions={len(actions)} | applied={len(applied)} | "
                f"Supabase adjusted rows={n_adj} | factor range "
                f"{status['min_adj_factor']:.9f}–{status['max_adj_factor']:.9f}"
            )
            time.sleep(0.10)

        except Exception as e:
            failed.append((ticker, str(e)))
            all_status.append({
                "ticker": ticker,
                "eod_rows": None,
                "corporate_actions": None,
                "applied_actions": None,
                "adjusted_rows_in_supabase": None,
                "min_adj_factor": None,
                "max_adj_factor": None,
                "status": "FAILED"
            })
            print(f"❌ {ticker}: {e}")

    status_df = pd.DataFrame(all_status)
    status_df.to_csv("adjust_110_status.csv", index=False, encoding="utf-8-sig")

    print("\n" + "="*90)
    print("FINAL SUMMARY")
    print("="*90)
    ok = int((status_df["status"] == "OK").sum())
    check = int((status_df["status"] == "CHECK").sum())
    fail = int((status_df["status"] == "FAILED").sum())
    print(f"OK (>=200 adjusted rows): {ok}/{len(UNIVERSE)}")
    print(f"CHECK: {check}")
    print(f"FAILED: {fail}")

    if failed:
        print("\nFailed tickers:")
        for t, msg in failed:
            print(f"  {t}: {msg}")

    if fail > 0:
        sys.exit(1)

    print("\n✅ 110-stock adjusted OHLC writeback completed.")


if __name__ == "__main__":
    main()
