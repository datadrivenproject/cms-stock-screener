import os
import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib


"""
CMS B exit-level tracker (display/reference only).

Purpose
-------
Add transparent exit-management reference fields to B_MasterList without
changing A selection logic and without sending automatic SELL/STOP alerts.

Rules
-----
1) ATR14 = 14-session SIMPLE average of True Range, exactly matching app.py.
2) Swing Low = the lowest adjusted Low from the KD20 setup window
   (the KD20 golden-cross day plus the previous 5 trading sessions).
3) System Stop = Swing Low - 0.5 * ATR14.
4) System TP1 = Entry + 1.0 * ATR14.
5) System TP2 = Entry + 2.0 * ATR14.
6) Daily KD80 bearish cross is displayed as a reference exit signal only.

Safety
------
- Does NOT modify app.py or A eligibility.
- Does NOT overwrite existing manual columns: 持仓止损 / TP1 / TP2.
- Does NOT send Telegram/email/push alerts.
- Reads market history from Supabase only; no BusinessQuant/Yahoo history calls.
"""

MARKET_TZ = ZoneInfo("America/New_York")
MASTER_SHEET = "B_MasterList"
LOOKBACK_ROWS = 90
KD_SIGNAL_LOOKBACK = 35

OUTPUT_COLUMNS = [
    "系统Entry",
    "ATR14参考",
    "Swing Low",
    "系统止损",
    "系统TP1",
    "系统TP2",
    "退出状态",
    "KD80死叉(日线)",
    "退出计算时间",
]


def _load_secrets():
    path = ".streamlit/secrets.toml"
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _find_value(obj, key):
    if isinstance(obj, dict):
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
        for v in obj.values():
            found = _find_value(v, key)
            if found not in (None, ""):
                return found
    return None


def _safe_float(x):
    try:
        if x is None:
            return np.nan
        s = str(x).strip().replace(",", "").replace("$", "")
        if not s or s.lower() in {"nan", "none", "na", "n/a"}:
            return np.nan
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except Exception:
        return np.nan


def _fmt(x):
    if x is None or not np.isfinite(x):
        return ""
    return f"{float(x):.2f}"


def _is_market_hours():
    # Manual override is useful for workflow_dispatch testing.
    if os.getenv("FORCE_B_EXIT_LEVELS", "0").strip() == "1":
        return True
    now = datetime.now(MARKET_TZ)
    return now.weekday() < 5 and time(9, 30) <= now.time() <= time(16, 0)


def _google_book(secrets):
    svc = secrets.get("gcp_service_account")
    tracker = secrets.get("tracker", {})
    sheet_name = tracker.get("sheet_name") if isinstance(tracker, dict) else None

    if not isinstance(svc, dict) or not sheet_name:
        raise RuntimeError("Missing [gcp_service_account] or [tracker].sheet_name in Streamlit secrets")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(dict(svc), scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(str(sheet_name))


def _supabase_config(secrets):
    url = os.getenv("SUPABASE_URL") or _find_value(secrets, "SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or _find_value(secrets, "SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")
    url = str(url).strip().rstrip("/")
    if "/rest/v1" in url:
        url = url.split("/rest/v1", 1)[0].rstrip("/")
    return url, str(key).strip()


def _fetch_daily(ticker, secrets):
    base, key = _supabase_config(secrets)
    endpoint = f"{base}/rest/v1/stock_daily"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    params = {
        "select": "trade_date,adj_open,adj_high,adj_low,adj_close,volume",
        "ticker": f"eq.{ticker}",
        "order": "trade_date.desc",
        "limit": str(LOOKBACK_ROWS),
    }
    r = requests.get(endpoint, headers=headers, params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Supabase {ticker} HTTP {r.status_code}: {r.text[:200]}")
    rows = r.json()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for c in ["adj_open", "adj_high", "adj_low", "adj_close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["trade_date", "adj_high", "adj_low", "adj_close"])
    return df.sort_values("trade_date").reset_index(drop=True)


def _add_daily_indicators(df):
    x = df.copy()
    high = x["adj_high"]
    low = x["adj_low"]
    close = x["adj_close"]

    # Same ATR14 definition as app.py: TR rolling(14).mean().
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["ATR14"] = tr.rolling(14).mean()

    # Same KDJ (9,3,3) convention as app.py.
    ll9 = low.rolling(9).min()
    hh9 = high.rolling(9).max()
    rsv = (close - ll9) / (hh9 - ll9).replace(0, np.nan) * 100.0
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    x["K"] = k
    x["D"] = d

    diff = k - d
    x["KD_CROSS_UP"] = (diff > 0) & (diff.shift(1) <= 0)
    x["KD_CROSS_DOWN"] = (diff < 0) & (diff.shift(1) >= 0)
    x["KD20_BUY"] = x["KD_CROSS_UP"] & (k <= 20) & (d <= 20)
    x["KD80_SELL"] = x["KD_CROSS_DOWN"] & (k >= 80) & (d >= 80)
    return x


def _latest_kd20_signal_idx(x):
    if x.empty:
        return None
    start = max(0, len(x) - KD_SIGNAL_LOOKBACK)
    idx = x.index[(x.index >= start) & x["KD20_BUY"].fillna(False)]
    if len(idx) == 0:
        return None
    return int(idx[-1])


def _system_levels(df, entry):
    if df.empty or len(df) < 15 or not np.isfinite(entry) or entry <= 0:
        return None

    x = _add_daily_indicators(df)
    atr = _safe_float(x.iloc[-1]["ATR14"])
    if not np.isfinite(atr) or atr <= 0:
        return None

    sig_idx = _latest_kd20_signal_idx(x)
    if sig_idx is None:
        return {
            "entry": entry,
            "atr": atr,
            "swing_low": np.nan,
            "stop": np.nan,
            "tp1": entry + atr,
            "tp2": entry + 2 * atr,
            "kd80_sell": bool(x.iloc[-1]["KD80_SELL"]),
        }

    # Transparent, no-look-ahead swing-low definition:
    # lowest Low on the KD20 signal day and the previous 5 sessions.
    left = max(0, sig_idx - 5)
    swing_low = _safe_float(x.loc[left:sig_idx, "adj_low"].min())
    stop = swing_low - 0.5 * atr if np.isfinite(swing_low) else np.nan

    return {
        "entry": entry,
        "atr": atr,
        "swing_low": swing_low,
        "stop": stop,
        "tp1": entry + atr,
        "tp2": entry + 2 * atr,
        "kd80_sell": bool(x.iloc[-1]["KD80_SELL"]),
    }


def _pick_entry(row):
    # Once actually bought, actual entry is the source of truth.
    actual = _safe_float(row.get("实际买入价"))
    if np.isfinite(actual) and actual > 0:
        return actual

    # Before purchase, use existing reference entry if available; otherwise last price.
    for col in ["参考入场", "最后价格", "价格", "Price"]:
        v = _safe_float(row.get(col))
        if np.isfinite(v) and v > 0:
            return v
    return np.nan


def _status(row, levels):
    if not levels:
        return "数据不足"

    price = np.nan
    for col in ["最后价格", "价格", "Price"]:
        v = _safe_float(row.get(col))
        if np.isfinite(v) and v > 0:
            price = v
            break

    if levels.get("kd80_sell"):
        return "SELL高位死叉（仅显示）"
    if np.isfinite(price):
        stop = levels.get("stop", np.nan)
        tp1 = levels.get("tp1", np.nan)
        tp2 = levels.get("tp2", np.nan)
        if np.isfinite(stop) and price <= stop:
            return "STOP触发（仅显示）"
        if np.isfinite(tp2) and price >= tp2:
            return "TP2 HIT"
        if np.isfinite(tp1) and price >= tp1:
            return "TP1 HIT"
    return "HOLD"


def _column_letter(n):
    # 1-based Excel/Sheets column number -> A, B, ..., AA...
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def main():
    if not _is_market_hours():
        print("Outside NY regular market hours; B exit-level display update skipped.")
        return

    secrets = _load_secrets()
    book = _google_book(secrets)
    ws = book.worksheet(MASTER_SHEET)

    records = ws.get_all_records()
    if not records:
        print("B_MasterList is empty; nothing to update.")
        return

    df = pd.DataFrame(records)
    if "股票代码" in df.columns and "Ticker" not in df.columns:
        df["Ticker"] = df["股票代码"]
    if "Ticker" not in df.columns:
        raise RuntimeError("B_MasterList missing Ticker/股票代码 column")

    now_text = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S ET")
    output = {c: [] for c in OUTPUT_COLUMNS}

    cache = {}
    for _, row in df.iterrows():
        ticker = str(row.get("Ticker", "")).strip().upper()
        entry = _pick_entry(row)

        if not ticker or not np.isfinite(entry) or entry <= 0:
            vals = {
                "系统Entry": "",
                "ATR14参考": "",
                "Swing Low": "",
                "系统止损": "",
                "系统TP1": "",
                "系统TP2": "",
                "退出状态": "未有Entry",
                "KD80死叉(日线)": "",
                "退出计算时间": now_text,
            }
        else:
            try:
                if ticker not in cache:
                    cache[ticker] = _fetch_daily(ticker, secrets)
                levels = _system_levels(cache[ticker], entry)
                vals = {
                    "系统Entry": _fmt(entry),
                    "ATR14参考": _fmt(levels.get("atr", np.nan)) if levels else "",
                    "Swing Low": _fmt(levels.get("swing_low", np.nan)) if levels else "",
                    "系统止损": _fmt(levels.get("stop", np.nan)) if levels else "",
                    "系统TP1": _fmt(levels.get("tp1", np.nan)) if levels else "",
                    "系统TP2": _fmt(levels.get("tp2", np.nan)) if levels else "",
                    "退出状态": _status(row, levels),
                    "KD80死叉(日线)": "是" if levels and levels.get("kd80_sell") else "否",
                    "退出计算时间": now_text,
                }
            except Exception as exc:
                print(f"WARNING {ticker}: {exc}")
                vals = {
                    "系统Entry": _fmt(entry),
                    "ATR14参考": "",
                    "Swing Low": "",
                    "系统止损": "",
                    "系统TP1": "",
                    "系统TP2": "",
                    "退出状态": "计算失败",
                    "KD80死叉(日线)": "",
                    "退出计算时间": now_text,
                }

        for c in OUTPUT_COLUMNS:
            output[c].append(vals[c])

    headers = ws.row_values(1)
    for c in OUTPUT_COLUMNS:
        if c not in headers:
            headers.append(c)
            ws.update_cell(1, len(headers), c)

    # Update only our own columns; never clear or overwrite the rest of B_MasterList.
    for c in OUTPUT_COLUMNS:
        col_num = headers.index(c) + 1
        letter = _column_letter(col_num)
        values = [[v] for v in output[c]]
        ws.update(values=values, range_name=f"{letter}2:{letter}{len(values) + 1}")

    print(f"✅ B exit-level display updated for {len(df)} rows")
    print("✅ A logic unchanged")
    print("✅ Existing 持仓止损 / TP1 / TP2 untouched")
    print("✅ No automatic SELL/STOP alerts sent")


if __name__ == "__main__":
    main()
