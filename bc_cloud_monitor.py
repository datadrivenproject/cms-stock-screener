#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS B/C FINAL v1.9 CLOUD MONITOR
--------------------------------
Purpose:
- Run the frozen B/C FINAL v1.8 LIVE logic headlessly in GitHub Actions.
- Every scheduled run:
  1) Read latest A_Candidates from Google Sheet.
  2) Sync A formal "买" candidates into B_MasterList.
  3) Monitor all real holdings + active A candidates.
  4) Pull Yahoo 60m + 15m data.
  5) Run the SAME B BUY/EARLY/WAIT/AVOID and C staged protection logic.
  6) Append B_Log and update B_MasterList.
- No Streamlit session is required.
- No A/B/C trading rule is changed.

Required GitHub repository secrets:
  GCP_SERVICE_ACCOUNT_JSON   = full Google service-account JSON
  TRACKER_SHEET_NAME         = Google Sheet workbook name
"""

import os
import sys
import json
import time as time_module
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

A_WORKSHEET = "A_Candidates"
B_LOG_WORKSHEET = "B_Log"
B_MASTER_WORKSHEET = "B_MasterList"

MARKET_TZ = ZoneInfo("America/New_York")
LIVE_INITIAL_STOP_MULTIPLIER = 1.50
MAX_CANDIDATES = 20

# Minimal aliases needed by A/B/C live pipeline.
SHEET_CN_MAP = {
    "Scan Date": "扫描日期",
    "Scan Time": "扫描时间",
    "Ticker": "股票代码",
    "Company": "公司",
    "Rank": "排名",
    "Confidence": "信心等级",
    "Fundamental Confirmation": "基本面确认",
    "Early V2 Score": "Early V2总分",
    "A5决策": "结果",
    "共振数": "共振数",
    "空间等级": "空间等级",
    "空间优先级": "空间优先级",
    "上方空间": "上方空间",
}
SHEET_INTERNAL_MAP = {v: k for k, v in SHEET_CN_MAP.items()}

B_MASTER_PRIMARY = [
    "Ticker","Company","池状态","是否持仓","A5决策","空间等级","空间优先级","上方空间",
    "最后决策","最后价格","实际买入价","持仓止损","参考入场","参考止损","TP1","TP2",
    "C阶段","持仓最高价","最高浮盈%","动态保护价","利润回吐%",
    "最近入选日期","跟踪天数","观察剩余天数","最后检查时间","最后决策依据",
    "Rank","共振数","Early V2 Score","Confidence","Fundamental Confirmation",
    "首次进入B","最近同步A","实际买入日期","退出日期","退出价","退出原因"
]

def log(msg):
    print(msg, flush=True)

def market_now():
    return datetime.now(MARKET_TZ)

def is_regular_market_hours(dt=None):
    dt = dt or market_now()
    if dt.weekday() >= 5:
        return False
    return time(9, 30) <= dt.time() <= time(16, 0)

def safe_float(x, default=np.nan):
    try:
        if x is None or pd.isna(x):
            return default
        s = str(x).strip().replace(",", "").replace("$", "")
        if not s or s.lower() in {"nan","none","n/a","na"}:
            return default
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except Exception:
        return default

def normalize_sheet_columns(df):
    if df is None or df.empty:
        return df
    return df.rename(columns={c: SHEET_INTERNAL_MAP.get(c, c) for c in df.columns})

def chinese_sheet_columns(df):
    if df is None:
        return df
    return df.rename(columns={c: SHEET_CN_MAP.get(c, c) for c in df.columns})

def get_book():
    raw = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_name = os.environ.get("TRACKER_SHEET_NAME", "").strip()
    if not raw:
        raise RuntimeError("Missing GitHub secret: GCP_SERVICE_ACCOUNT_JSON")
    if not sheet_name:
        raise RuntimeError("Missing GitHub secret: TRACKER_SHEET_NAME")

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GCP_SERVICE_ACCOUNT_JSON is not valid JSON: {e}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(sheet_name)

def get_or_create_ws(name, rows=3000, cols=80):
    book = get_book()
    try:
        return book.worksheet(name)
    except Exception:
        return book.add_worksheet(title=name, rows=rows, cols=cols)

def load_sheet(name):
    ws = get_or_create_ws(name)
    rec = ws.get_all_records()
    if not rec:
        return pd.DataFrame()
    df = normalize_sheet_columns(pd.DataFrame(rec))
    if "Ticker" in df.columns:
        df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    return df

def load_latest_a_candidates():
    df = load_sheet(A_WORKSHEET)
    if df.empty:
        return pd.DataFrame(), None
    if "Ticker" not in df.columns:
        raise RuntimeError("A_Candidates missing 股票代码/Ticker")

    date_col = next((c for c in ["Scan Date","Date","日期","扫描日期"] if c in df.columns), None)
    if date_col is None:
        raise RuntimeError("A_Candidates missing 扫描日期")

    df["_scan_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df[df["_scan_date"].notna()].copy()
    if df.empty:
        return pd.DataFrame(), None

    latest_day = df["_scan_date"].max()
    today = df[df["_scan_date"].eq(latest_day)].copy()
    today["Ticker"] = today["Ticker"].astype(str).str.strip().str.upper()
    today = today.drop_duplicates("Ticker", keep="last")

    if "A5决策" not in today.columns:
        raise RuntimeError("A_Candidates missing 结果/A5决策")
    today = today[today["A5决策"].astype(str).str.strip().eq("买")].copy()

    if "Rank" in today.columns:
        today["Rank"] = pd.to_numeric(today["Rank"], errors="coerce")
        today = today.sort_values("Rank", ascending=True, na_position="last")

    if not today.empty:
        today["最近入选日期"] = latest_day.strftime("%Y-%m-%d")
        today["跟踪天数"] = 1
        today["观察剩余天数"] = 5
        today["池状态"] = "TRACKING"

    return today.reset_index(drop=True), latest_day.strftime("%Y-%m-%d")

def load_b_master():
    return load_sheet(B_MASTER_WORKSHEET)

def save_b_master(df):
    ws = get_or_create_ws(B_MASTER_WORKSHEET, rows=2000, cols=100)
    x = df.copy() if df is not None else pd.DataFrame()
    x = x.replace([np.inf, -np.inf], np.nan).fillna("")
    first = [c for c in B_MASTER_PRIMARY if c in x.columns]
    rest = [c for c in x.columns if c not in first]
    x = chinese_sheet_columns(x[first + rest].copy())
    ws.clear()
    if not x.empty:
        ws.update(values=[list(x.columns)] + x.astype(str).values.tolist(), range_name="A1")
    return True

def business_day_age(last_date, current_date):
    try:
        d1 = pd.to_datetime(last_date).normalize()
        d2 = pd.to_datetime(current_date).normalize()
        if pd.isna(d1) or pd.isna(d2):
            return np.nan
        if d2 < d1:
            return 1
        return len(pd.bdate_range(d1, d2))
    except Exception:
        return np.nan

def sync_master_with_a(master, today_a, scan_date):
    now = market_now().strftime("%Y-%m-%d %H:%M:%S")
    current_day = pd.to_datetime(scan_date, errors="coerce")
    if pd.isna(current_day):
        current_day = pd.Timestamp(market_now().date())
    current_day = current_day.normalize()
    current_day_str = current_day.strftime("%Y-%m-%d")

    m = master.copy() if master is not None else pd.DataFrame()
    if m.empty:
        m = pd.DataFrame(columns=["Ticker"])
    if "Ticker" not in m.columns:
        m["Ticker"] = ""
    m["Ticker"] = m["Ticker"].astype(str).str.strip().str.upper()
    m = m.drop_duplicates("Ticker", keep="last").copy()

    defaults = {
        "是否持仓": "否", "池状态": "TRACKING", "首次进入B": "",
        "最近入选日期": "", "跟踪天数": "", "观察剩余天数": "", "最近同步A": ""
    }
    for c, default in defaults.items():
        if c not in m.columns:
            m[c] = default

    for idx, row in m.iterrows():
        is_holding = str(row.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]
        if is_holding:
            m.at[idx, "池状态"] = "HOLDING"
            m.at[idx, "观察剩余天数"] = "持仓不受限"
            continue
        age = business_day_age(row.get("最近入选日期",""), current_day)
        if pd.isna(age):
            m.at[idx, "池状态"] = "TRACKING"
            continue
        age = int(age)
        m.at[idx, "跟踪天数"] = age
        m.at[idx, "观察剩余天数"] = max(0, 6 - age)
        m.at[idx, "池状态"] = "TRACKING" if age <= 5 else "EXPIRED"

    a = today_a.copy() if today_a is not None else pd.DataFrame()
    if not a.empty:
        a["Ticker"] = a["Ticker"].astype(str).str.strip().str.upper()
        a = a.drop_duplicates("Ticker", keep="last")

    rows = {
        str(r.get("Ticker","")).strip().upper(): r.to_dict()
        for _, r in m.iterrows()
        if str(r.get("Ticker","")).strip()
    }

    protected = {
        "首次进入B","是否持仓","实际买入日期","实际买入价","持仓止损",
        "TP1","TP2","退出日期","退出价","退出原因"
    }

    for _, arow in a.iterrows():
        t = str(arow.get("Ticker","")).strip().upper()
        if not t:
            continue
        old = rows.get(t, {})
        new = dict(old)
        for k, v in arow.to_dict().items():
            if k not in protected:
                new[k] = v
        new["Ticker"] = t
        if not old.get("首次进入B"):
            new["首次进入B"] = now
        new["最近入选日期"] = current_day_str
        new["跟踪天数"] = 1
        new["观察剩余天数"] = 5
        new["最近同步A"] = now

        is_holding = str(old.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]
        new["是否持仓"] = "是" if is_holding else "否"
        new["池状态"] = "HOLDING" if is_holding else "TRACKING"
        rows[t] = new

    out = pd.DataFrame(list(rows.values())) if rows else pd.DataFrame(columns=["Ticker"])
    if not out.empty:
        out["Ticker"] = out["Ticker"].astype(str).str.upper()
        state_order = {"HOLDING":0, "TRACKING":1, "EXPIRED":2, "CLOSED":3}
        out["_state_order"] = out["池状态"].map(state_order).fillna(9)
        out = out.sort_values(["_state_order","Ticker"], kind="stable").drop(columns="_state_order")
    return out.reset_index(drop=True)

def active_master_pool(master, max_candidates=20):
    if master is None or master.empty:
        return pd.DataFrame()
    x = master.copy()
    hold = x[x["池状态"].astype(str).eq("HOLDING")].copy() if "池状态" in x.columns else pd.DataFrame()
    watch = x[x["池状态"].astype(str).eq("TRACKING")].copy() if "池状态" in x.columns else pd.DataFrame()

    if not watch.empty and "A5决策" in watch.columns:
        watch = watch[watch["A5决策"].astype(str).str.strip().eq("买")].copy()

    if not watch.empty:
        watch["_room_priority"] = pd.to_numeric(
            watch["空间优先级"] if "空间优先级" in watch.columns else 0, errors="coerce"
        ).fillna(0)
        watch["_rank"] = pd.to_numeric(
            watch["Rank"] if "Rank" in watch.columns else np.nan, errors="coerce"
        )
        sort_cols = ["最近入选日期","_room_priority","_rank"]
        watch = watch.sort_values(sort_cols, ascending=[False,False,True], na_position="last")
        watch = watch.drop(columns=["_room_priority","_rank"])

    watch = watch.head(max_candidates)
    return pd.concat([hold, watch], ignore_index=True, sort=False).drop_duplicates("Ticker", keep="first")

def flatten_yf(df):
    if df is None or df.empty:
        return None
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = x.columns.get_level_values(0)
    for c in ["Open","High","Low","Close","Volume"]:
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    if not all(c in x.columns for c in ["High","Low","Close","Volume"]):
        return None
    return x.dropna(subset=["High","Low","Close","Volume"])

def get_intraday(ticker, interval, period):
    last_err = None
    for attempt in range(3):
        try:
            df = yf.download(
                ticker, interval=interval, period=period, auto_adjust=True,
                progress=False, threads=False, prepost=False
            )
            x = flatten_yf(df)
            if x is not None and not x.empty:
                return x
        except Exception as e:
            last_err = e
        time_module.sleep(2 + attempt * 2)
    log(f"⚠️ {ticker} {interval} Yahoo data unavailable: {last_err}")
    return None

def calc_rsi(close, period=14):
    d = close.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.rolling(period).mean()
    al = loss.rolling(period).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100/(1+rs)

def calc_atr(df, period=14):
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"]-df["Low"],
        (df["High"]-prev).abs(),
        (df["Low"]-prev).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def add_indicators(df):
    x = df.copy()
    x["EMA9"] = x["Close"].ewm(span=9, adjust=False).mean()
    x["EMA20"] = x["Close"].ewm(span=20, adjust=False).mean()
    x["EMA50"] = x["Close"].ewm(span=50, adjust=False).mean()
    e12 = x["Close"].ewm(span=12, adjust=False).mean()
    e26 = x["Close"].ewm(span=26, adjust=False).mean()
    x["MACD"] = e12-e26
    x["MACD_SIGNAL"] = x["MACD"].ewm(span=9, adjust=False).mean()
    x["MACD_HIST"] = x["MACD"]-x["MACD_SIGNAL"]
    x["RSI14"] = calc_rsi(x["Close"],14)
    x["ATR14"] = calc_atr(x,14)
    typical = (x["High"]+x["Low"]+x["Close"])/3
    session = pd.Series(x.index.date,index=x.index)
    x["VWAP"] = (typical*x["Volume"]).groupby(session).cumsum() / x["Volume"].groupby(session).cumsum().replace(0,np.nan)
    return x

def evaluate_1h(df):
    if df is None or len(df) < 30:
        return {"valid":False,"status":"DATA","reason":"1H数据不足"}
    x = add_indicators(df)
    r=x.iloc[-1]; p=x.iloc[-2]
    price=safe_float(r["Close"]); e20=safe_float(r["EMA20"]); e50=safe_float(r["EMA50"])
    rsi=safe_float(r["RSI14"]); hist=safe_float(r["MACD_HIST"]); histp=safe_float(p["MACD_HIST"])
    trend = price>e20 and e20>=e50*0.995
    momentum = hist>0 or hist>histp
    healthy = 48<=rsi<=72
    if trend and momentum and healthy:
        status="强"; reason="1H趋势与动量同步，RSI健康"
    elif trend and momentum:
        status="中等"; reason="1H趋势仍在，但RSI位置一般"
    else:
        status="弱"; reason="1H趋势或动量未确认"
    return {"valid":True,"status":status,"reason":reason,"rsi":rsi}

def evaluate_15m(df):
    if df is None or len(df) < 40:
        return {"valid":False,"reason":"15min数据不足"}
    x=add_indicators(df)
    r=x.iloc[-1]; prev=x.iloc[-2]; prev20=x.iloc[-21:-1]
    price=safe_float(r["Close"]); vwap=safe_float(r["VWAP"]); e9=safe_float(r["EMA9"]); e20=safe_float(r["EMA20"])
    rsi=safe_float(r["RSI14"]); atr=safe_float(r["ATR14"]); hist=safe_float(r["MACD_HIST"]); histp=safe_float(prev["MACD_HIST"])
    avgvol=safe_float(prev20["Volume"].mean())
    volratio=safe_float(r["Volume"])/avgvol if avgvol>0 else np.nan
    ph=safe_float(prev20["High"].max())
    breakout = price>ph if not pd.isna(ph) else False
    near = (-0.004 <= (ph-price)/ph <= 0.012) if (not pd.isna(ph) and ph>0) else False
    above_vwap = price>=vwap if not pd.isna(vwap) else False
    ema_structure = price>e9>=e20 if not any(pd.isna(z) for z in [price,e9,e20]) else False
    macd_improving = hist>0 or hist>histp
    pullback = False
    if not any(pd.isna(z) for z in [price,vwap,e9,e20,atr]) and atr>0:
        pullback = price>=max(vwap,e20) and abs(price-e9)<=0.40*atr
    base=max(vwap,e20) if not any(pd.isna(z) for z in [vwap,e20]) else np.nan
    ext=(price-base)/base if not pd.isna(base) and base>0 else np.nan
    overextended = (not pd.isna(ext) and ext>0.025) or (not pd.isna(rsi) and rsi>75)
    breakout_extension = ((price-ph)/ph) if (breakout and not pd.isna(ph) and ph>0) else np.nan
    macd_positive = (hist > 0) if not pd.isna(hist) else False
    return {
        "valid":True,"price":price,"vwap":vwap,"ema9":e9,"ema20":e20,"rsi":rsi,"atr":atr,
        "volratio":volratio,"breakout":breakout,"near":near,"above_vwap":above_vwap,
        "ema_structure":ema_structure,"macd_improving":macd_improving,"macd_positive":macd_positive,
        "breakout_extension":breakout_extension,"pullback":pullback,"overextended":overextended
    }

def decision(row,h1,m15):
    if not h1.get("valid"):
        return "⚪ DATA", h1.get("reason","1H数据不足"), np.nan, np.nan
    if not m15.get("valid"):
        return "⚪ DATA", m15.get("reason","15min数据不足"), np.nan, np.nan
    if h1["status"]=="弱":
        return "🔴 AVOID","1H趋势/动量未确认",np.nan,np.nan
    if m15["overextended"]:
        return "🟡 WAIT","偏离VWAP/EMA20过大或RSI过热，避免追高",np.nan,np.nan
    if not m15["above_vwap"]:
        return "🟡 WAIT","价格仍在VWAP下方",np.nan,np.nan

    breakout_ext = safe_float(m15.get("breakout_extension", np.nan))
    breakout_rsi_ok = (not pd.isna(m15["rsi"])) and 50 <= m15["rsi"] <= 70
    breakout_not_chasing = pd.isna(breakout_ext) or breakout_ext <= 0.008

    breakout_buy = (
        h1["status"]=="强"
        and m15["breakout"]
        and m15["ema_structure"]
        and m15.get("macd_positive", False)
        and breakout_rsi_ok
        and breakout_not_chasing
        and not pd.isna(m15["volratio"])
        and m15["volratio"]>=1.50
    )

    pullback_buy = (
        h1["status"] in ["强","中等"]
        and m15["pullback"]
        and m15["macd_improving"]
        and (pd.isna(m15["volratio"]) or m15["volratio"]>=0.80)
    )

    if breakout_buy:
        stop=min(m15["vwap"],m15["ema20"])-0.35*m15["atr"]
        return "🟢 BUY","V2.1突破确认：1H强 + 15min真实突破 + MACD为正 + RSI 50–70 + 量比≥1.50 + 突破不追高",m15["price"],stop
    if pullback_buy:
        stop=min(m15["vwap"],m15["ema20"])-0.35*m15["atr"]
        return "🟢 BUY","1H趋势保持 + 15min健康回踩 + 动量改善",m15["price"],stop
    if m15["near"] and m15["macd_improving"] and m15["above_vwap"]:
        return "🟠 EARLY BUY","接近15min突破位，动量改善且位于VWAP上方；等待正式突破/回踩确认",np.nan,np.nan
    return "🟡 WAIT","结构尚可，但15min触发条件未齐",np.nan,np.nan

def apply_live_initial_stop(entry_px, base_stop):
    entry_px = safe_float(entry_px, np.nan)
    base_stop = safe_float(base_stop, np.nan)
    if pd.isna(entry_px) or entry_px <= 0:
        return np.nan
    if pd.isna(base_stop) or base_stop <= 0 or base_stop >= entry_px:
        return base_stop
    base_dist = entry_px - base_stop
    return max(0.01, entry_px - LIVE_INITIAL_STOP_MULTIPLIER * base_dist)

def buy_gate_diagnosis(h1, m15):
    if not h1.get("valid"):
        return "1H数据不足"
    if not m15.get("valid"):
        return "15m数据不足"

    br = {
        "1H强": h1.get("status") == "强",
        "突破": bool(m15.get("breakout")),
        "EMA结构": bool(m15.get("ema_structure")),
        "MACD正": bool(m15.get("macd_positive")),
        "RSI50-70": (not pd.isna(safe_float(m15.get("rsi", np.nan))) and 50 <= safe_float(m15.get("rsi", np.nan)) <= 70),
        "量比≥1.50": (not pd.isna(safe_float(m15.get("volratio", np.nan))) and safe_float(m15.get("volratio", np.nan)) >= 1.50),
        "不追高": (pd.isna(safe_float(m15.get("breakout_extension", np.nan))) or safe_float(m15.get("breakout_extension", np.nan)) <= 0.008),
    }
    pb = {
        "1H≥中等": h1.get("status") in ["强","中等"],
        "回踩": bool(m15.get("pullback")),
        "MACD改善": bool(m15.get("macd_improving")),
        "量比≥0.80": (pd.isna(safe_float(m15.get("volratio", np.nan))) or safe_float(m15.get("volratio", np.nan)) >= 0.80),
    }
    br_fail = [k for k,v in br.items() if not v]
    pb_fail = [k for k,v in pb.items() if not v]
    if not br_fail:
        return "突破BUY全部通过"
    if not pb_fail:
        return "回踩BUY全部通过"
    return f"突破缺：{'、'.join(br_fail[:4])}；回踩缺：{'、'.join(pb_fail[:4])}"

def _high_since_entry(df15, entry_dt, fallback_price=np.nan):
    if df15 is None or df15.empty:
        return fallback_price
    try:
        x = df15.copy()
        hi = pd.to_numeric(x["High"], errors="coerce")
        if entry_dt is not None and not pd.isna(entry_dt):
            try:
                if getattr(x.index, "tz", None) is not None and getattr(entry_dt, "tzinfo", None) is None:
                    entry_dt = entry_dt.tz_localize(x.index.tz)
                elif getattr(x.index, "tz", None) is None and getattr(entry_dt, "tzinfo", None) is not None:
                    entry_dt = entry_dt.tz_localize(None)
            except Exception:
                pass
            try:
                hi = hi.loc[x.index >= entry_dt]
            except Exception:
                pass
        v = safe_float(hi.max(), np.nan)
        if pd.isna(v):
            return fallback_price
        return max(v, fallback_price) if not pd.isna(fallback_price) else v
    except Exception:
        return fallback_price

def calc_c_stage(entry, original_stop, peak_price):
    if pd.isna(entry) or entry <= 0 or pd.isna(peak_price):
        return "C0 初始保护", original_stop, np.nan
    peak_ret = peak_price / entry - 1.0
    stop0 = original_stop if (not pd.isna(original_stop) and original_stop > 0) else np.nan

    if peak_ret < 0.04:
        stage = "C0 初始保护"; dyn = stop0
    elif peak_ret < 0.06:
        stage = "C1 保本区"
        vals = [v for v in [stop0, entry*0.9975] if not pd.isna(v)]
        dyn = max(vals) if vals else np.nan
    elif peak_ret < 0.10:
        stage = "C2 利润保护"
        vals = [v for v in [stop0, entry*(1+max(0.02, peak_ret*0.40))] if not pd.isna(v)]
        dyn = max(vals) if vals else np.nan
    else:
        stage = "C3 强趋势保护"
        vals = [v for v in [stop0, entry*(1+max(0.04, peak_ret*0.60))] if not pd.isna(v)]
        dyn = max(vals) if vals else np.nan
    return stage, dyn, peak_ret*100.0

def c_trend_warning(h1, m15):
    if not h1.get("valid") or not m15.get("valid"):
        return False
    price=safe_float(m15.get("price",np.nan)); vwap=safe_float(m15.get("vwap",np.nan)); e20=safe_float(m15.get("ema20",np.nan))
    below = (
        not pd.isna(price) and
        ((not pd.isna(vwap) and price < vwap) or (not pd.isna(e20) and price < e20))
    )
    return h1.get("status") == "弱" and below

def analyze_holding(row):
    ticker = str(row["Ticker"]).strip().upper()
    h1_df = get_intraday(ticker, "60m", "3mo")
    m15_df = get_intraday(ticker, "15m", "10d")
    h1 = evaluate_1h(h1_df)
    m15 = evaluate_15m(m15_df)

    price=safe_float(m15.get("price",np.nan))
    entry=safe_float(row.get("实际买入价",np.nan))
    original_stop=safe_float(row.get("持仓止损",np.nan))
    tp1=safe_float(row.get("TP1",np.nan))
    tp2=safe_float(row.get("TP2",np.nan))

    entry_dt=pd.to_datetime(row.get("实际买入日期",""), errors="coerce")
    peak_price=_high_since_entry(m15_df, entry_dt, fallback_price=price)
    stage,dynamic_stop,peak_ret_pct=calc_c_stage(entry,original_stop,peak_price)
    pnl=((price-entry)/entry*100) if (not pd.isna(price) and not pd.isna(entry) and entry>0) else np.nan
    giveback=peak_ret_pct-pnl if (not pd.isna(peak_ret_pct) and not pd.isna(pnl)) else np.nan
    trend_warn=c_trend_warning(h1,m15)

    if pd.isna(price):
        d="⚪ DATA"; reason="持仓行情数据不足"
    elif not pd.isna(original_stop) and original_stop>0 and price<=original_stop:
        d="🛑 STOP LOSS"; reason=f"现价{price:.2f}已触及原始止损{original_stop:.2f}"
    elif stage in ["C1 保本区","C2 利润保护","C3 强趋势保护"] and not pd.isna(dynamic_stop) and dynamic_stop>0 and price<=dynamic_stop:
        d="🔻 PROFIT PROTECT"; reason=f"{stage}触发动态保护：现价{price:.2f} ≤ 保护价{dynamic_stop:.2f}"
    elif not pd.isna(tp2) and tp2>0 and price>=tp2:
        d="🟣 TAKE PROFIT TP2"; reason=f"现价{price:.2f}已达到TP2 {tp2:.2f}"
    elif not pd.isna(tp1) and tp1>0 and price>=tp1:
        d="🟠 TAKE PROFIT TP1"; reason=f"现价{price:.2f}已达到TP1 {tp1:.2f}；可考虑分批止盈"
    elif trend_warn and not pd.isna(pnl) and pnl>0:
        d="🟡 HOLD / 趋势转弱"; reason="1H转弱且15m跌回VWAP/EMA20下方；先警戒"
    else:
        d="🟢 HOLD"
        reason="尚未达到+4%峰值，继续使用原始止损" if stage=="C0 初始保护" else f"{stage}；动态保护价{dynamic_stop:.2f}"

    return {
        "Ticker":ticker,"最近入选日期":row.get("最近入选日期",""),"跟踪天数":row.get("跟踪天数",""),
        "观察剩余天数":"持仓不受限","池状态":"HOLDING","A结果":row.get("A5决策",""),
        "A空间等级":row.get("空间等级",""),"A空间优先级":row.get("空间优先级",""),
        "A上方空间":row.get("上方空间",np.nan),"A排名":row.get("Rank",""),"A共振数":row.get("共振数",""),
        "A Early V2":row.get("Early V2 Score",""),"A信心":row.get("Confidence",""),
        "A基本面":row.get("Fundamental Confirmation",""),"当前价格":price,"盘中决策":d,
        "决策依据":reason,"持仓成本":entry,"持仓盈亏%":pnl,"C阶段":stage,"持仓最高价":peak_price,
        "最高浮盈%":peak_ret_pct,"动态保护价":dynamic_stop,"利润回吐%":giveback,
        "趋势转弱警报":"是" if trend_warn else "否","1H状态":h1.get("status","DATA"),
        "1H RSI":h1.get("rsi",np.nan),"15m VWAP":m15.get("vwap",np.nan),"15m EMA9":m15.get("ema9",np.nan),
        "15m EMA20":m15.get("ema20",np.nan),"15m RSI":m15.get("rsi",np.nan),
        "15m量比":m15.get("volratio",np.nan),"15m突破":"是" if m15.get("breakout") else "否",
        "15m回踩":"是" if m15.get("pullback") else "否","VWAP上方":"是" if m15.get("above_vwap") else "否",
        "避免追高":"是" if m15.get("overextended") else "否","参考入场":entry,
        "参考止损":original_stop,"TP1":tp1,"TP2":tp2
    }

def analyze_one(row):
    is_holding = (
        str(row.get("池状态","")).upper() == "HOLDING" or
        str(row.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]
    )
    if is_holding:
        return analyze_holding(row)

    ticker=str(row["Ticker"]).strip().upper()
    h1=evaluate_1h(get_intraday(ticker,"60m","3mo"))
    m15=evaluate_15m(get_intraday(ticker,"15m","10d"))
    d,reason,entry,base_stop=decision(row,h1,m15)
    stop=apply_live_initial_stop(entry,base_stop)
    if d=="🟢 BUY" and not pd.isna(safe_float(stop,np.nan)):
        reason += f"；V1.8初始Stop采用原止损距离×{LIVE_INITIAL_STOP_MULTIPLIER:.2f}"

    return {
        "Ticker":ticker,"最近入选日期":row.get("最近入选日期",""),"跟踪天数":row.get("跟踪天数",""),
        "观察剩余天数":row.get("观察剩余天数",""),"池状态":row.get("池状态","TRACKING"),
        "A结果":row.get("A5决策",""),"A空间等级":row.get("空间等级",""),
        "A空间优先级":row.get("空间优先级",""),"A上方空间":row.get("上方空间",np.nan),
        "A排名":row.get("Rank",""),"A共振数":row.get("共振数",""),"A Early V2":row.get("Early V2 Score",""),
        "A信心":row.get("Confidence",""),"A基本面":row.get("Fundamental Confirmation",""),
        "当前价格":m15.get("price",np.nan),"盘中决策":d,"决策依据":reason,
        "BUY门槛诊断":buy_gate_diagnosis(h1,m15),"1H状态":h1.get("status","DATA"),
        "1H RSI":h1.get("rsi",np.nan),"15m VWAP":m15.get("vwap",np.nan),
        "15m EMA9":m15.get("ema9",np.nan),"15m EMA20":m15.get("ema20",np.nan),
        "15m RSI":m15.get("rsi",np.nan),"15m量比":m15.get("volratio",np.nan),
        "15m突破":"是" if m15.get("breakout") else "否","15m回踩":"是" if m15.get("pullback") else "否",
        "VWAP上方":"是" if m15.get("above_vwap") else "否","避免追高":"是" if m15.get("overextended") else "否",
        "1H强":"是" if h1.get("status")=="强" else "否",
        "1H至少中等":"是" if h1.get("status") in ["强","中等"] else "否",
        "15m EMA结构":"是" if m15.get("ema_structure") else "否",
        "15m MACD正":"是" if m15.get("macd_positive") else "否",
        "15m MACD改善":"是" if m15.get("macd_improving") else "否",
        "突破RSI合格":"是" if (not pd.isna(safe_float(m15.get("rsi",np.nan))) and 50<=safe_float(m15.get("rsi",np.nan))<=70) else "否",
        "突破量比≥1.50":"是" if (not pd.isna(safe_float(m15.get("volratio",np.nan))) and safe_float(m15.get("volratio",np.nan))>=1.50) else "否",
        "回踩量比≥0.80":"是" if (pd.isna(safe_float(m15.get("volratio",np.nan))) or safe_float(m15.get("volratio",np.nan))>=0.80) else "否",
        "突破不追高":"是" if (pd.isna(safe_float(m15.get("breakout_extension",np.nan))) or safe_float(m15.get("breakout_extension",np.nan))<=0.008) else "否",
        "接近突破位":"是" if m15.get("near") else "否","参考入场":entry,
        "基础止损":base_stop,"参考止损":stop
    }

def load_previous_b_states():
    df = load_sheet(B_LOG_WORKSHEET)
    if df.empty or "Ticker" not in df.columns or "盘中决策" not in df.columns:
        return {}
    if "检查时间" in df.columns:
        df["_dt"] = pd.to_datetime(df["检查时间"], errors="coerce")
        df = df.sort_values("_dt")
    latest = df.drop_duplicates("Ticker", keep="last")
    return dict(zip(latest["Ticker"].astype(str).str.upper(), latest["盘中决策"].astype(str)))

def append_b_log(out, run_time):
    ws = get_or_create_ws(B_LOG_WORKSHEET, rows=10000, cols=100)
    if out is None or out.empty:
        return False
    log_df = out.copy()
    log_df.insert(0,"检查时间",run_time.strftime("%Y-%m-%d %H:%M:%S"))
    log_df.insert(1,"检查日期",run_time.strftime("%Y-%m-%d"))
    log_df = chinese_sheet_columns(log_df.replace([np.inf,-np.inf],np.nan).fillna(""))
    existing = ws.get_all_values()
    headers = list(log_df.columns)
    if not existing or existing[0] != headers:
        ws.clear()
        ws.update(values=[headers] + log_df.astype(str).values.tolist(), range_name="A1")
    else:
        ws.append_rows(log_df.astype(str).values.tolist(), value_input_option="USER_ENTERED")
    return True

def run_monitor():
    now = market_now()
    force = os.environ.get("FORCE_RUN", "").strip() == "1"

    log("="*88)
    log(f"CMS B/C v1.9 CLOUD MONITOR | {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log("="*88)

    # Scheduled workflow is intentionally broad in UTC; Python decides actual ET window.
    if not force and not is_regular_market_hours(now):
        log("⏭ Outside regular US market hours (09:30–16:00 ET). Skip.")
        return 0

    today_a, scan_date = load_latest_a_candidates()
    master = load_b_master()
    master = sync_master_with_a(master, today_a, scan_date)
    save_b_master(master)

    monitor = active_master_pool(master, MAX_CANDIDATES)
    if monitor.empty:
        log("ℹ️ No active B candidates or real holdings.")
        return 0

    previous = load_previous_b_states()
    rows = []

    for i, (_, row) in enumerate(monitor.iterrows(), 1):
        ticker = str(row.get("Ticker","")).strip().upper()
        log(f"[{i}/{len(monitor)}] Analyze {ticker}")
        result = analyze_one(row)
        rows.append(result)
        log(
            f"    {result.get('盘中决策','')} | "
            f"px={safe_float(result.get('当前价格',np.nan)):.2f} | "
            f"1H={result.get('1H状态','')} | "
            f"reason={result.get('决策依据','')}"
        )

    out = pd.DataFrame(rows)
    out["上一轮状态"] = out["Ticker"].map(previous).fillna("首次检查")
    out["状态变化"] = out.apply(
        lambda r: (
            f"{r['上一轮状态']} → {r['盘中决策']}"
            if r["上一轮状态"] != "首次检查" and r["上一轮状态"] != r["盘中决策"]
            else ("首次检查" if r["上一轮状态"] == "首次检查" else "无变化")
        ),
        axis=1
    )
    out["新BUY提醒"] = out.apply(
        lambda r: "🔔 新BUY"
        if r["盘中决策"] == "🟢 BUY" and r["上一轮状态"] != "🟢 BUY"
        else "",
        axis=1
    )

    order = {
        "🛑 STOP LOSS":0,"🔻 PROFIT PROTECT":1,"🟣 TAKE PROFIT TP2":2,
        "🟠 TAKE PROFIT TP1":3,"🟢 BUY":4,"🟠 EARLY BUY":5,
        "🟡 HOLD / 趋势转弱":6,"🟢 HOLD":7,"🟡 WAIT":8,"🔴 AVOID":9,"⚪ DATA":10
    }
    out["_o"] = out["盘中决策"].map(order).fillna(9)
    sort_cols = ["_o"] + (["A排名"] if "A排名" in out.columns else [])
    out = out.sort_values(sort_cols).drop(columns="_o").reset_index(drop=True)

    append_b_log(out, now)

    mm = master.copy()
    for _, rr in out.iterrows():
        mask = mm["Ticker"].astype(str).str.upper().eq(str(rr["Ticker"]).upper())
        if not mask.any():
            continue
        mm.loc[mask,"最后检查时间"] = now.strftime("%Y-%m-%d %H:%M:%S")
        mm.loc[mask,"最后价格"] = rr.get("当前价格","")
        mm.loc[mask,"最后决策"] = rr.get("盘中决策","")
        mm.loc[mask,"最后决策依据"] = rr.get("决策依据","")

        is_hold = (
            mm.loc[mask,"是否持仓"].astype(str).isin(["是","Y","YES","TRUE","1"]).any()
            if "是否持仓" in mm.columns else False
        )

        if is_hold:
            for c in ["C阶段","持仓最高价","最高浮盈%","动态保护价","利润回吐%"]:
                if c in rr.index:
                    mm.loc[mask,c] = rr.get(c,"")
        else:
            entry = safe_float(rr.get("参考入场",np.nan))
            stop = safe_float(rr.get("参考止损",np.nan))
            if not pd.isna(entry):
                mm.loc[mask,"参考入场"] = rr.get("参考入场","")
            if not pd.isna(stop):
                mm.loc[mask,"参考止损"] = rr.get("参考止损","")

    save_b_master(mm)

    changed = out[out["状态变化"].astype(str).ne("无变化")]
    if not changed.empty:
        log("\nSTATE CHANGES:")
        for _, r in changed.iterrows():
            log(f"  {r['Ticker']}: {r['状态变化']}")

    new_buys = out[out["新BUY提醒"].eq("🔔 新BUY")]
    if not new_buys.empty:
        log("\n🚨 NEW BUY:")
        for _, r in new_buys.iterrows():
            log(f"  {r['Ticker']} @ {safe_float(r.get('当前价格',np.nan)):.2f} | {r.get('决策依据','')}")

    c_actions = out[out["盘中决策"].isin(
        ["🛑 STOP LOSS","🔻 PROFIT PROTECT","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"]
    )]
    if not c_actions.empty:
        log("\n🚨 C ACTION:")
        for _, r in c_actions.iterrows():
            log(f"  {r['Ticker']}: {r['盘中决策']} | {r.get('决策依据','')}")

    log(f"\n✅ Completed: {len(out)} symbols. B_Log + B_MasterList updated.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(run_monitor())
    except Exception as e:
        log(f"❌ FATAL: {type(e).__name__}: {e}")
        raise
