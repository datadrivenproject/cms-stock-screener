#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import math
import io
import time
import requests
import pandas as pd
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

# =========================================================
# CMS A6 FINAL — ADJUST 500+ STOCK POOL
# Purpose:
#   1) Build same A6 FINAL universe:
#      current S&P 500 + original CMS core/watchlist
#   2) Add 12 benchmark ETFs
#   3) Read raw OHLC already stored in Supabase
#   4) Fetch corporate actions from Business Quant in batches
#   5) Rebuild adj_open / adj_high / adj_low / adj_close / adj_factor
#   6) Upsert only adjusted fields back to stock_daily
# =========================================================

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

BENCHMARKS_12 = [
    "SPY","XLK","XLV","XLF","XLY","XLP",
    "XLI","XLE","XLB","XLU","XLRE","XLC"
]

SP500_SOURCES = [
    "https://raw.githubusercontent.com/chinobing/historical_sp500_constituents/refs/heads/main/sp500_constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
]

BQ_CORP_URL = "https://data.businessquant.com/corporate_actions"
CORP_ACTION_BATCH = 50
DB_PAGE_SIZE = 1000
DB_WRITE_BATCH = 500
MIN_ADJUSTED_ROWS = 200
MAX_RETRIES = 3
NY = ZoneInfo("America/New_York")


def fail(msg):
    print(f"❌ {msg}", flush=True)
    sys.exit(1)


def env(name):
    v = os.getenv(name, "").strip()
    if not v:
        fail(f"Missing GitHub Secret: {name}")
    return v


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def fnum(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def headers(key):
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }


def get_sp500_tickers():
    for url in SP500_SOURCES:
        try:
            r = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 CMS-A6-FINAL"}
            )
            print(f"S&P500 source HTTP {r.status_code}: {url}")
            if not r.ok or not r.text.strip():
                continue

            df = pd.read_csv(io.StringIO(r.text))
            symbol_col = next(
                (
                    c for c in df.columns
                    if str(c).strip().lower() in {"symbol", "ticker", "tickers"}
                ),
                None
            )
            if symbol_col is None:
                continue

            tickers = (
                df[symbol_col]
                .astype(str)
                .str.upper()
                .str.strip()
                .str.replace(".", "-", regex=False)
                .tolist()
            )
            tickers = list(dict.fromkeys(
                t for t in tickers if t and t != "NAN"
            ))

            if len(tickers) >= 450:
                return tickers

        except Exception as e:
            print(f"⚠️ S&P500 source failed: {e}")

    fail("无法取得有效 S&P 500 股票名单；本次停止。")


def build_universe():
    sp500 = get_sp500_tickers()
    stocks = list(dict.fromkeys(sp500 + CORE_UNIVERSE))
    tickers = list(dict.fromkeys(stocks + BENCHMARKS_12))

    print(f"当前 S&P 500 ticker: {len(sp500)}")
    print(f"CMS Core/watchlist: {len(CORE_UNIVERSE)}")
    print(f"A6 正式股票池(去重): {len(stocks)}")
    print(f"Benchmark ETFs: {len(BENCHMARKS_12)}")
    print(f"本次需调整总 ticker: {len(tickers)}")

    return stocks, tickers


def fetch_raw(sb_url, sb_key, ticker):
    url = f"{sb_url.rstrip('/')}/rest/v1/stock_daily"
    out = []
    offset = 0

    while True:
        p = {
            "select": "ticker,trade_date,open,high,low,close,volume",
            "ticker": f"eq.{ticker}",
            "order": "trade_date.asc",
            "limit": DB_PAGE_SIZE,
            "offset": offset
        }
        r = requests.get(
            url,
            headers=headers(sb_key),
            params=p,
            timeout=120
        )
        if not r.ok:
            raise RuntimeError(
                f"Supabase read {ticker} HTTP {r.status_code}: {r.text[:800]}"
            )

        rows = r.json()
        out.extend(rows)

        if len(rows) < DB_PAGE_SIZE:
            break
        offset += DB_PAGE_SIZE

    clean = []
    for x in out:
        row = {
            "ticker": ticker,
            "trade_date": str(x.get("trade_date", ""))[:10],
            "open": fnum(x.get("open")),
            "high": fnum(x.get("high")),
            "low": fnum(x.get("low")),
            "close": fnum(x.get("close")),
            "volume": x.get("volume")
        }
        if (
            row["trade_date"]
            and all(row[k] is not None for k in ["open","high","low","close"])
        ):
            clean.append(row)

    clean.sort(key=lambda z: z["trade_date"])
    return clean


def normalize_actions(payload, allowed_tickers):
    out = defaultdict(list)
    allowed = set(allowed_tickers)

    def add(ticker, item):
        if not isinstance(item, dict):
            return

        t = str(
            ticker
            or item.get("ticker")
            or item.get("symbol")
            or ""
        ).upper().strip()

        action = str(
            item.get("action")
            or item.get("type")
            or item.get("action_type")
            or ""
        ).lower().strip()

        date = str(
            item.get("date")
            or item.get("ex_date")
            or item.get("event_date")
            or ""
        )[:10]

        value = fnum(
            item.get("value")
            if item.get("value") is not None
            else item.get("ratio")
        )

        if (
            t in allowed
            and action in {"split", "dividend"}
            and date
            and value is not None
        ):
            out[t].append({
                "date": date,
                "action": action,
                "value": value
            })

    if isinstance(payload, list):
        for item in payload:
            add(None, item)

    elif isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            for item in payload["data"]:
                add(None, item)

        for key, block in payload.items():
            if key in {"data", "metadata", "meta", "status"}:
                continue

            if isinstance(block, dict) and isinstance(block.get("data"), list):
                for item in block["data"]:
                    add(key, item)
            elif isinstance(block, list):
                for item in block:
                    add(key, item)
            elif isinstance(block, dict):
                add(key, block)

    for t in list(out):
        seen = set()
        cleaned = []

        for x in sorted(
            out[t],
            key=lambda z: (z["date"], z["action"], z["value"])
        ):
            sig = (x["date"], x["action"], x["value"])
            if sig not in seen:
                cleaned.append(x)
                seen.add(sig)

        out[t] = cleaned

    return dict(out)


def fetch_actions_batch(api_key, batch):
    params = {
        "ticker": ",".join(batch),
        "period": "10y",
        "api_key": api_key
    }

    last = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                BQ_CORP_URL,
                params=params,
                timeout=180
            )

            print(
                f"  Corporate actions HTTP {r.status_code} "
                f"for {len(batch)} symbols",
                flush=True
            )

            if r.status_code == 404:
                return {}

            if r.status_code == 429:
                raise RuntimeError(
                    f"Business Quant rate limit: {r.text[:800]}"
                )

            if not r.ok:
                raise RuntimeError(
                    f"Business Quant HTTP {r.status_code}: {r.text[:1200]}"
                )

            return normalize_actions(r.json(), batch)

        except Exception as e:
            last = e
            print(f"  ⚠️ 第 {attempt} 次 corporate actions 请求失败: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)

    raise last


def fetch_actions(api_key, tickers):
    """
    Old 122 version sent every symbol in ONE URL.
    For 500+ symbols that is unnecessarily fragile, so this version batches.
    """
    merged = defaultdict(list)
    batches = list(chunks(tickers, CORP_ACTION_BATCH))

    print(
        f"📥 Corporate actions: {len(tickers)} symbols "
        f"in {len(batches)} batches"
    )

    for i, batch in enumerate(batches, 1):
        print(
            f"\nCorporate-actions batch {i}/{len(batches)} "
            f"({len(batch)} symbols)"
        )

        try:
            amap = fetch_actions_batch(api_key, batch)
        except Exception as e:
            print(f"❌ Batch failed: {e}")
            # Important: do not silently assume "no actions" when a request failed.
            raise

        for t, acts in amap.items():
            merged[t].extend(acts)

        time.sleep(0.5)

    # final de-dup
    final = {}
    for t, acts in merged.items():
        seen = set()
        cleaned = []
        for x in sorted(
            acts,
            key=lambda z: (z["date"], z["action"], z["value"])
        ):
            sig = (x["date"], x["action"], x["value"])
            if sig not in seen:
                cleaned.append(x)
                seen.add(sig)
        final[t] = cleaned

    return final


def build_adjusted(raw, actions):
    if not raw:
        return []

    by_date = {r["trade_date"]: r for r in raw}
    dates = [r["trade_date"] for r in raw]
    factors = {d: 1.0 for d in dates}

    for a in sorted(actions, key=lambda z: z["date"]):
        adate = a["date"]
        val = fnum(a["value"])

        if val is None or val <= 0:
            continue

        if a["action"] == "split":
            mult = 1.0 / val
        else:
            prev = [d for d in dates if d < adate]
            if not prev:
                continue

            pc = fnum(by_date[prev[-1]]["close"])
            if pc is None or pc <= 0:
                continue

            mult = (pc - val) / pc
            if not (0 < mult <= 1):
                continue

        for d in dates:
            if d < adate:
                factors[d] *= mult

    out = []

    for r in raw:
        f = factors[r["trade_date"]]
        out.append({
            "ticker": r["ticker"],
            "trade_date": r["trade_date"],
            "adj_open": round(r["open"] * f, 10),
            "adj_high": round(r["high"] * f, 10),
            "adj_low": round(r["low"] * f, 10),
            "adj_close": round(r["close"] * f, 10),
            "adj_factor": round(f, 12)
        })

    return out


def upsert(sb_url, sb_key, rows):
    if not rows:
        return

    url = f"{sb_url.rstrip('/')}/rest/v1/stock_daily"
    h = headers(sb_key)
    h["Prefer"] = "resolution=merge-duplicates,return=minimal"

    for i in range(0, len(rows), DB_WRITE_BATCH):
        b = rows[i:i+DB_WRITE_BATCH]

        r = requests.post(
            url,
            params={"on_conflict": "ticker,trade_date"},
            headers=h,
            json=b,
            timeout=180
        )

        if not r.ok:
            raise RuntimeError(
                f"Supabase upsert HTTP {r.status_code}: {r.text[:1200]}"
            )


def main():
    bq = env("BUSINESSQUANT_API_KEY")
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    if "/rest/v1" in sb_url:
        fail("SUPABASE_URL 必须是项目基础 URL，不能包含 /rest/v1")

    stocks, tickers = build_universe()

    print("=" * 88)
    print("CMS A6 FINAL — ADJUST 500+ EXISTING SUPABASE OHLC")
    print(datetime.now(NY).strftime("%Y-%m-%d %H:%M:%S %Z"))
    print("Raw OHLC preserved. Only adj_* fields are rebuilt.")
    print("=" * 88)

    amap = fetch_actions(bq, tickers)

    ok = 0
    check = 0
    total = 0
    no_raw = []

    for i, t in enumerate(tickers, 1):
        print(
            f"\n[{i:03d}/{len(tickers)}] {t}",
            flush=True
        )

        raw = fetch_raw(sb_url, sb_key, t)

        if not raw:
            print("    ❌ no raw rows")
            no_raw.append(t)
            check += 1
            continue

        acts = amap.get(t, [])
        adj = build_adjusted(raw, acts)
        upsert(sb_url, sb_key, adj)

        total += len(adj)

        splits = sum(1 for x in acts if x["action"] == "split")
        divs = sum(1 for x in acts if x["action"] == "dividend")

        print(
            f"    raw={len(raw)} adjusted={len(adj)} "
            f"splits={splits} dividends={divs} "
            f"latest={raw[-1]['trade_date']}"
        )

        if len(adj) >= MIN_ADJUSTED_ROWS:
            ok += 1
        else:
            check += 1

    print("\n" + "=" * 88)
    print("FINAL SUMMARY")
    print(f"A6 正式股票池: {len(stocks)}")
    print(f"含 benchmark 后总 ticker: {len(tickers)}")
    print(f"OK (>={MIN_ADJUSTED_ROWS} adjusted rows): {ok}/{len(tickers)}")
    print(f"CHECK: {check}")
    print(f"Adjusted rows written: {total}")

    if no_raw:
        print(
            f"⚠️ No raw rows ({len(no_raw)}): "
            + ", ".join(no_raw[:80])
        )
        if len(no_raw) > 80:
            print(f"   ...另有 {len(no_raw)-80} 只")

    if ok == len(tickers):
        print("✅ 全部股票 adjusted OHLC successfully stored in Supabase.")
        print("✅ Raw OHLC preserved. A6 FINAL logic unchanged.")
    else:
        print(
            "⚠️ 部分 ticker 未达到调整数据要求。"
            "通常先重新运行 load_stock_daily_529.py 补 raw 数据，"
            "然后再运行本程序即可。"
        )
        fail(
            f"Adjustment validation incomplete: "
            f"{ok}/{len(tickers)}"
        )


if __name__ == "__main__":
    main()
