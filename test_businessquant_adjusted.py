#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS Business Quant adjusted-price validation
----------------------------------------------
Purpose:
1) Pull 1-year raw EOD OHLCV from Business Quant.
2) Pull Business Quant corporate actions (dividend + split).
3) Build a backward-adjusted OHLC series.
4) Compare raw BQ and adjusted BQ with Yahoo Finance auto_adjust=True.
5) Compare MA20 / RSI14 / MACD histogram.
6) Save summary/detail CSVs as GitHub Actions artifacts.

This is a TEST ONLY. It does not write to Supabase and does not modify A5.2R.
"""

import os
import sys
import math
import json
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf


TICKERS = ["AAPL", "NVDA", "TSLA", "PLUG", "TEM"]
BQ_BASE = "https://data.businessquant.com"
TIMEOUT = 30


def safe_float(x):
    try:
        if x is None or x == "":
            return np.nan
        return float(x)
    except Exception:
        return np.nan


def request_json(url: str, params: Dict[str, Any]) -> Any:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    print(f"HTTP {r.status_code}: {r.url.split('api_key=')[0]}api_key=***")
    r.raise_for_status()
    return r.json()


def extract_data_block(payload: Any, ticker: str = "") -> Tuple[List[dict], Dict[str, Any]]:
    """
    Robustly extracts Business Quant response rows from:
      {"data":[...], "metadata":{...}}
    or multi-ticker:
      {"AAPL":{"data":[...], "metadata":{...}}, ...}
    or a plain list.
    """
    if isinstance(payload, list):
        return payload, {}

    if not isinstance(payload, dict):
        return [], {}

    if ticker and ticker in payload and isinstance(payload[ticker], dict):
        block = payload[ticker]
        return block.get("data", []) or [], block.get("metadata", {}) or {}

    if "data" in payload:
        return payload.get("data", []) or [], payload.get("metadata", {}) or {}

    # Last-resort: find the first nested dict containing "data"
    for v in payload.values():
        if isinstance(v, dict) and "data" in v:
            return v.get("data", []) or [], v.get("metadata", {}) or {}

    return [], payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}


def fetch_bq_eod(ticker: str, period: str = "1y") -> pd.DataFrame:
    payload = request_json(
        f"{BQ_BASE}/quotes",
        {
            "ticker": ticker,
            "mode": "eod",
            "period": period,
            "limit": 10000,
            "page": 1,
            "api_key": API_KEY,
        },
    )
    rows, _ = extract_data_block(payload, ticker)
    if not rows:
        raise RuntimeError(f"{ticker}: Business Quant EOD returned no rows")

    df = pd.DataFrame(rows)
    # Accept likely date field names
    date_col = next((c for c in ["date", "pricedate", "trade_date"] if c in df.columns), None)
    if not date_col:
        raise RuntimeError(f"{ticker}: cannot find date field in EOD response: {list(df.columns)}")

    rename = {date_col: "date"}
    for c in df.columns:
        cl = c.lower()
        if cl in {"open", "high", "low", "close", "volume"}:
            rename[c] = cl
    df = df.rename(columns=rename)

    need = ["date", "open", "high", "low", "close", "volume"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise RuntimeError(f"{ticker}: missing EOD fields {miss}; available={list(df.columns)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Business Quant can occasionally return duplicate dates.
    # Keep the API's last returned record for that date, matching our loader convention.
    before = len(df)
    df = df.dropna(subset=["date", "close"]).drop_duplicates(subset=["date"], keep="last")
    if len(df) != before:
        print(f"  {ticker}: deduped {before-len(df)} EOD duplicate/invalid rows")
    return df.sort_values("date").reset_index(drop=True)


def fetch_bq_actions(ticker: str, period: str = "1y") -> pd.DataFrame:
    all_rows: List[dict] = []
    page = 1
    while True:
        payload = request_json(
            f"{BQ_BASE}/corporate_actions",
            {
                "ticker": ticker,
                "action": "dividend,split",
                "period": period,
                "limit": 10000,
                "page": page,
                "api_key": API_KEY,
            },
        )
        rows, meta = extract_data_block(payload, ticker)
        all_rows.extend(rows)

        pagination = meta.get("pagination", {}) if isinstance(meta, dict) else {}
        total_pages = pagination.get("total_pages")
        if total_pages is None:
            # With limit=10000 one page is enough for a 1y test unless API says otherwise.
            break
        if page >= int(total_pages):
            break
        page += 1

    if not all_rows:
        return pd.DataFrame(columns=["date", "action", "value", "notes"])

    df = pd.DataFrame(all_rows)
    for c in ["date", "action", "value", "notes"]:
        if c not in df.columns:
            df[c] = np.nan
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    df["action"] = df["action"].astype(str).str.lower().str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_yahoo_adjusted(ticker: str, period: str = "1y") -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        actions=False,
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"{ticker}: Yahoo returned no rows")

    # yfinance may return MultiIndex columns.
    if isinstance(df.columns, pd.MultiIndex):
        if ticker in df.columns.get_level_values(-1):
            try:
                df = df.xs(ticker, axis=1, level=-1)
            except Exception:
                df.columns = df.columns.get_level_values(0)
        else:
            df.columns = df.columns.get_level_values(0)

    out = df.reset_index()
    date_col = "Date" if "Date" in out.columns else out.columns[0]
    out = out.rename(columns={
        date_col: "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["date", "close"]).sort_values("date")


def parse_split_ratio(value: float, notes: str = "") -> float:
    """
    Business Quant docs define split value as a ratio:
      4.0 = 4-for-1
      0.05 = 20-for-1 reverse split
    Return new_shares / old_shares.
    """
    if pd.notna(value) and value > 0:
        return float(value)
    return np.nan


def build_backward_adjusted(raw: pd.DataFrame, actions: pd.DataFrame) -> Tuple[pd.DataFrame, List[dict]]:
    """
    Build Yahoo-style backward adjusted OHLC from raw BQ OHLC.

    For a split with ratio r = new shares / old shares:
      all dates before split date get price factor *= 1/r

    For a cash dividend D on ex-date:
      all dates before ex-date get price factor *= (Pprev - D) / Pprev
    where Pprev is the last raw close before the ex-date.

    The factor is applied to O/H/L/C. Volume is left untouched here because
    this validation is focused on matching Yahoo auto_adjust price inputs used by A.
    """
    out = raw.copy().sort_values("date").reset_index(drop=True)
    out["adj_factor"] = 1.0
    applied = []

    for _, a in actions.sort_values("date").iterrows():
        adate = a["date"]
        action = str(a["action"]).lower()
        value = safe_float(a["value"])
        notes = "" if pd.isna(a.get("notes")) else str(a.get("notes"))

        prior_mask = out["date"] < adate
        if not prior_mask.any():
            continue

        event_factor = np.nan

        if action == "split":
            ratio = parse_split_ratio(value, notes)
            if pd.notna(ratio) and ratio > 0:
                event_factor = 1.0 / ratio

        elif action == "dividend":
            if pd.notna(value) and value >= 0:
                prev_rows = out.loc[prior_mask, ["date", "close"]].dropna()
                if not prev_rows.empty:
                    pprev = float(prev_rows.iloc[-1]["close"])
                    if pprev > 0 and value < pprev:
                        event_factor = (pprev - value) / pprev

        if pd.notna(event_factor) and event_factor > 0:
            out.loc[prior_mask, "adj_factor"] *= float(event_factor)
            applied.append({
                "date": adate.date().isoformat(),
                "action": action,
                "value": value,
                "factor": float(event_factor),
                "notes": notes,
            })

    for c in ["open", "high", "low", "close"]:
        out[c] = out[c] * out["adj_factor"]

    return out, applied


def rsi14(s: pd.Series) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd_hist(s: pd.Series) -> pd.Series:
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def pct_abs(a: pd.Series, b: pd.Series) -> pd.Series:
    denom = b.abs().replace(0, np.nan)
    return (a - b).abs() / denom * 100.0


def compare_one(ticker: str):
    print("\n" + "=" * 78)
    print(f"🔎 {ticker}")
    print("=" * 78)

    raw = fetch_bq_eod(ticker)
    acts = fetch_bq_actions(ticker)
    adj, applied = build_backward_adjusted(raw, acts)
    yah = fetch_yahoo_adjusted(ticker)

    print(f"BQ EOD rows={len(raw)} | Yahoo rows={len(yah)} | actions={len(acts)} | applied={len(applied)}")
    if applied:
        for x in applied:
            print(f"  ACTION {x['date']} {x['action']} value={x['value']} factor={x['factor']:.10f} {x['notes']}")
    else:
        print("  No dividend/split adjustment applied in the 1y window.")

    base = raw.merge(
        adj[["date", "open", "high", "low", "close", "adj_factor"]].rename(columns={
            "open":"adj_open","high":"adj_high","low":"adj_low","close":"adj_close"
        }),
        on="date",
        how="inner",
    ).merge(
        yah.rename(columns={
            "open":"y_open","high":"y_high","low":"y_low","close":"y_close","volume":"y_volume"
        }),
        on="date",
        how="inner",
    )

    if base.empty:
        raise RuntimeError(f"{ticker}: no common trading dates")

    raw_close_diff = pct_abs(base["close"], base["y_close"])
    adj_close_diff = pct_abs(base["adj_close"], base["y_close"])

    # Indicators calculated on each full common-date close sequence
    base = base.sort_values("date").reset_index(drop=True)
    base["raw_ma20"] = base["close"].rolling(20).mean()
    base["adj_ma20"] = base["adj_close"].rolling(20).mean()
    base["y_ma20"] = base["y_close"].rolling(20).mean()

    base["raw_rsi"] = rsi14(base["close"])
    base["adj_rsi"] = rsi14(base["adj_close"])
    base["y_rsi"] = rsi14(base["y_close"])

    base["raw_macdh"] = macd_hist(base["close"])
    base["adj_macdh"] = macd_hist(base["adj_close"])
    base["y_macdh"] = macd_hist(base["y_close"])

    last = base.iloc[-1]

    def absnum(a, b):
        if pd.isna(a) or pd.isna(b):
            return np.nan
        return abs(float(a) - float(b))

    row = {
        "Ticker": ticker,
        "共同交易日": len(base),
        "BQ行动数": len(acts),
        "实际应用行动数": len(applied),
        "原始Close平均差异%": raw_close_diff.mean(),
        "复权Close平均差异%": adj_close_diff.mean(),
        "原始Close最大差异%": raw_close_diff.max(),
        "复权Close最大差异%": adj_close_diff.max(),
        "原始最新Close差异%": float(raw_close_diff.iloc[-1]),
        "复权最新Close差异%": float(adj_close_diff.iloc[-1]),
        "原始MA20差异": absnum(last["raw_ma20"], last["y_ma20"]),
        "复权MA20差异": absnum(last["adj_ma20"], last["y_ma20"]),
        "原始RSI差异": absnum(last["raw_rsi"], last["y_rsi"]),
        "复权RSI差异": absnum(last["adj_rsi"], last["y_rsi"]),
        "原始MACD柱差异": absnum(last["raw_macdh"], last["y_macdh"]),
        "复权MACD柱差异": absnum(last["adj_macdh"], last["y_macdh"]),
    }

    improved = (
        pd.notna(row["复权Close平均差异%"])
        and pd.notna(row["原始Close平均差异%"])
        and row["复权Close平均差异%"] < row["原始Close平均差异%"]
    )
    row["复权是否改善"] = "✅ 是" if improved else "⚠️ 否/无明显改善"

    print(
        f"共同日={len(base)} | "
        f"Close平均差异: 原始={row['原始Close平均差异%']:.6f}% → 复权={row['复权Close平均差异%']:.6f}% | "
        f"最大: 原始={row['原始Close最大差异%']:.6f}% → 复权={row['复权Close最大差异%']:.6f}% | "
        f"{row['复权是否改善']}"
    )
    print(
        f"最新指标差异 | "
        f"MA20 {row['原始MA20差异']:.6f} → {row['复权MA20差异']:.6f} | "
        f"RSI {row['原始RSI差异']:.6f} → {row['复权RSI差异']:.6f} | "
        f"MACD柱 {row['原始MACD柱差异']:.6f} → {row['复权MACD柱差异']:.6f}"
    )

    detail = base[[
        "date",
        "open","high","low","close",
        "adj_open","adj_high","adj_low","adj_close","adj_factor",
        "y_open","y_high","y_low","y_close",
    ]].copy()
    detail.insert(0, "ticker", ticker)

    actions_out = acts.copy()
    if not actions_out.empty:
        actions_out.insert(0, "checked_ticker", ticker)

    return row, detail, actions_out


if __name__ == "__main__":
    API_KEY = os.environ.get("BUSINESSQUANT_API_KEY", "").strip()
    if not API_KEY:
        print("❌ Missing GitHub secret: BUSINESSQUANT_API_KEY")
        sys.exit(2)

    print("CMS Adjusted Data Test — Business Quant corporate actions vs Yahoo auto_adjust=True")
    print("Tickers:", ", ".join(TICKERS))

    summaries = []
    details = []
    actions_all = []
    failures = []

    for t in TICKERS:
        try:
            s, d, a = compare_one(t)
            summaries.append(s)
            details.append(d)
            if not a.empty:
                actions_all.append(a)
        except Exception as e:
            failures.append((t, str(e)))
            print(f"❌ {t} FAILED: {e}")

    if summaries:
        summary_df = pd.DataFrame(summaries)
        print("\n" + "=" * 100)
        print("汇总")
        print("=" * 100)
        print(summary_df.to_string(index=False))
        summary_df.to_csv("businessquant_adjusted_summary.csv", index=False, encoding="utf-8-sig")

    if details:
        pd.concat(details, ignore_index=True).to_csv(
            "businessquant_adjusted_detail.csv", index=False, encoding="utf-8-sig"
        )

    if actions_all:
        pd.concat(actions_all, ignore_index=True).to_csv(
            "businessquant_corporate_actions.csv", index=False, encoding="utf-8-sig"
        )
    else:
        pd.DataFrame(columns=["checked_ticker","date","ticker","action","value","notes"]).to_csv(
            "businessquant_corporate_actions.csv", index=False, encoding="utf-8-sig"
        )

    if failures:
        print("\n失败项:")
        for t, msg in failures:
            print(f"  {t}: {msg}")
        # Fail workflow only if every ticker failed; partial output remains available.
        if len(failures) == len(TICKERS):
            sys.exit(1)

    print("\n✅ Test finished. No Supabase or A5.2R data was modified.")
