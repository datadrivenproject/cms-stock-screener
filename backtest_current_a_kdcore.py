#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""60-trading-day benchmark for the CURRENT formal A KD-Core.

Read-only research script. It does NOT change app.py, A_Candidates, B/C, or Supabase.
It does NOT call BusinessQuant/Yahoo and does NOT download market history elsewhere.

Formal A eligibility is reproduced exactly from current app.py:
  strict KD20 golden cross
  + prior/current 5D return <= -3%
  + ATR14 / close >= 4%
Strong tier: 5D return <= -5% with the same KD20 + ATR requirement.

KDJ and ATR formulas match current app.py. Each historical signal is calculated only
from bars available on that date. A production-like minimum of 210 as-of-date bars
is required before a ticker can generate a signal.
"""

import io
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

TABLE = "stock_daily"
PAGE_SIZE = 1000
BACKTEST_DAYS = 60
FORWARD_DAYS = 5
MIN_ASOF_ROWS = 210
OUT = Path("output")

# Keep the same extra growth/hot-stock pool used by current app.py.
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


def env(name):
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing GitHub Secret: {name}")
    return v


def get_current_a_universe():
    sources = [
        "https://raw.githubusercontent.com/chinobing/historical_sp500_constituents/refs/heads/main/sp500_constituents.csv",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    ]
    for url in sources:
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent":"Mozilla/5.0 Current-A-Backtest"})
            r.raise_for_status()
            x = pd.read_csv(io.StringIO(r.text))
            col = next((c for c in x.columns if str(c).strip().lower() in {"symbol","ticker","tickers"}), None)
            if col is None:
                continue
            sp = (x[col].astype(str).str.upper().str.strip().str.replace(".", "-", regex=False).tolist())
            sp = list(dict.fromkeys(t for t in sp if t and t != "NAN"))
            if len(sp) >= 450:
                return list(dict.fromkeys(sp + CORE_UNIVERSE))
        except Exception:
            continue
    raise RuntimeError("Could not load current S&P 500 universe; refusing to use a smaller fallback.")


def load_supabase_rows(universe):
    base = env("SUPABASE_URL").rstrip("/")
    if "/rest/v1" in base:
        base = base.split("/rest/v1", 1)[0].rstrip("/")
    key = env("SUPABASE_SERVICE_ROLE_KEY")
    endpoint = f"{base}/rest/v1/{TABLE}"
    headers = {"apikey":key, "Authorization":f"Bearer {key}", "Accept":"application/json"}

    # Pull only the current A universe from the existing adjusted Supabase table.
    # Chunk ticker filters so URLs stay modest; paginate every chunk.
    rows = []
    for c0 in range(0, len(universe), 80):
        chunk = universe[c0:c0+80]
        offset = 0
        ticker_filter = "(" + ",".join(chunk) + ")"
        while True:
            params = {
                "select":"ticker,trade_date,adj_open,adj_high,adj_low,adj_close,volume",
                "ticker":f"in.{ticker_filter}",
                "order":"ticker.asc,trade_date.asc",
                "limit":str(PAGE_SIZE),
                "offset":str(offset),
            }
            r = requests.get(endpoint, headers=headers, params=params, timeout=60)
            r.raise_for_status()
            batch = r.json()
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        print(f"loaded universe {min(c0+80,len(universe))}/{len(universe)} | rows={len(rows)}", flush=True)

    if not rows:
        raise RuntimeError("No adjusted Supabase rows returned")
    z = pd.DataFrame(rows)
    z["trade_date"] = pd.to_datetime(z["trade_date"], errors="coerce")
    for c in ["adj_open","adj_high","adj_low","adj_close","volume"]:
        z[c] = pd.to_numeric(z[c], errors="coerce")
    z = z.dropna(subset=["ticker","trade_date","adj_high","adj_low","adj_close","volume"])
    return z.sort_values(["ticker","trade_date"])


def current_a_signal(d):
    """Exact formal eligibility ingredients from current app.py, as-of last row."""
    if len(d) < MIN_ASOF_ROWS:
        return None
    close = d["adj_close"]
    high = d["adj_high"]
    low = d["adj_low"]

    ll9 = low.rolling(9).min()
    hh9 = high.rolling(9).max()
    rsv = (close - ll9) / (hh9 - ll9).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    dd = k.ewm(alpha=1/3, adjust=False).mean()
    kd_diff = k - dd
    kd_cross = bool(kd_diff.iloc[-1] > 0 and kd_diff.iloc[-2] <= 0)
    kd_low20 = bool(k.iloc[-1] <= 20 and dd.iloc[-1] <= 20)
    kd20 = bool(kd_cross and kd_low20)

    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().iloc[-1]
    price = close.iloc[-1]
    atr_pct = atr14 / price if pd.notna(atr14) and price > 0 else np.nan

    # Matches app.py pct_return(close, 5): current / 5 sessions ago - 1.
    ret5 = close.iloc[-1] / close.iloc[-6] - 1 if len(close) >= 6 and close.iloc[-6] > 0 else np.nan

    formal = bool(kd20 and pd.notna(ret5) and ret5 <= -0.03 and pd.notna(atr_pct) and atr_pct >= 0.04)
    strong = bool(formal and ret5 <= -0.05)
    return formal, strong, float(k.iloc[-1]), float(dd.iloc[-1]), float(ret5), float(atr_pct)


def main():
    universe = get_current_a_universe()
    print(f"Current A 60D backtest | requested universe={len(universe)}", flush=True)
    all_rows = load_supabase_rows(universe)
    data = {t:g.reset_index(drop=True) for t,g in all_rows.groupby("ticker", sort=False)}
    available = [t for t in universe if t in data]
    missing = [t for t in universe if t not in data]
    print(f"Supabase available={len(available)} | missing={len(missing)}", flush=True)

    # Same 60 market dates for all stocks, ending 5 sessions before freshest date.
    market_dates = sorted(all_rows["trade_date"].dropna().unique())
    if len(market_dates) < BACKTEST_DAYS + FORWARD_DAYS:
        raise RuntimeError("Not enough market dates for 60D + 5D forward benchmark")
    signal_dates = set(market_dates[-(BACKTEST_DAYS+FORWARD_DAYS):-FORWARD_DAYS])

    signals = []
    for n,ticker in enumerate(available,1):
        d = data[ticker]
        date_to_i = {dt:i for i,dt in enumerate(d["trade_date"])}
        for dt in signal_dates:
            i = date_to_i.get(pd.Timestamp(dt))
            if i is None or i < MIN_ASOF_ROWS-1 or i + FORWARD_DAYS >= len(d):
                continue
            sig = current_a_signal(d.iloc[:i+1])
            if sig is None or not sig[0]:
                continue
            formal,strong,k0,d0,ret5,atr_pct = sig
            entry = float(d.loc[i,"adj_close"])
            f3 = d.iloc[i+1:i+4]["adj_high"]
            f5 = d.iloc[i+1:i+6]
            if entry <= 0 or len(f5) < 5:
                continue
            max3 = float(f3.max()/entry-1)*100 if len(f3) else np.nan
            max5 = float(f5["adj_high"].max()/entry-1)*100
            close5 = float(f5["adj_close"].iloc[-1]/entry-1)*100
            dd5 = float(f5["adj_low"].min()/entry-1)*100
            signals.append({
                "ticker":ticker,"signal_date":pd.Timestamp(dt).date().isoformat(),
                "tier":"强反弹候选" if strong else "优选候选",
                "entry_close":entry,"K":k0,"D":d0,"5D_return_signal":ret5*100,"ATR_pct":atr_pct*100,
                "3D_max_gain_pct":max3,"5D_max_gain_pct":max5,"5D_close_return_pct":close5,"5D_max_drawdown_pct":dd5,
            })
        if n % 50 == 0:
            print(f"processed {n}/{len(available)} | signals={len(signals)}", flush=True)

    s = pd.DataFrame(signals)
    if s.empty:
        raise RuntimeError("Current A produced zero historical signals")

    n = len(s)
    days = s["signal_date"].nunique()
    summary = pd.DataFrame([{
        "样本数":n,
        "信号交易日数":days,
        "平均每天候选数":n/BACKTEST_DAYS,
        "3D最大涨幅均值%":s["3D_max_gain_pct"].mean(),
        "5D最大涨幅均值%":s["5D_max_gain_pct"].mean(),
        "5D最大涨幅中位数%":s["5D_max_gain_pct"].median(),
        "5D>=3%":(s["5D_max_gain_pct"]>=3).mean()*100,
        "5D>=5%":(s["5D_max_gain_pct"]>=5).mean()*100,
        "5D>=8%":(s["5D_max_gain_pct"]>=8).mean()*100,
        "弱股<2%":(s["5D_max_gain_pct"]<2).mean()*100,
        "平均最大回撤%":s["5D_max_drawdown_pct"].mean(),
        "5D收盘收益均值%":s["5D_close_return_pct"].mean(),
        "5D收盘正收益率":(s["5D_close_return_pct"]>0).mean()*100,
    }])
    by_tier = s.groupby("tier").agg(
        样本数=("ticker","size"),
        平均5D最大涨幅=("5D_max_gain_pct","mean"),
        平均最大回撤=("5D_max_drawdown_pct","mean"),
    ).reset_index()
    by_tier["5D>=5%"] = s.groupby("tier")["5D_max_gain_pct"].apply(lambda x:(x>=5).mean()*100).values
    by_tier["5D>=8%"] = s.groupby("tier")["5D_max_gain_pct"].apply(lambda x:(x>=8).mean()*100).values
    by_tier["弱股<2%"] = s.groupby("tier")["5D_max_gain_pct"].apply(lambda x:(x<2).mean()*100).values

    OUT.mkdir(exist_ok=True)
    s.to_csv(OUT/"current_a_60d_signals.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT/"current_a_60d_summary.csv", index=False, encoding="utf-8-sig")
    by_tier.to_csv(OUT/"current_a_60d_by_tier.csv", index=False, encoding="utf-8-sig")

    print("\n=== Current A KD-Core 60D Summary ===", flush=True)
    print(summary.round(3).to_string(index=False), flush=True)
    print("\n=== By Tier ===", flush=True)
    print(by_tier.round(3).to_string(index=False), flush=True)
    print("\nREAD-ONLY benchmark complete. No production A/B/C logic was changed.", flush=True)


if __name__ == "__main__":
    main()
