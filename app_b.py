import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time
from zoneinfo import ZoneInfo

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

st.set_page_config(page_title="CMS V4.3B V1.5 — Master Watchlist", page_icon="🎯", layout="wide")
st.title("🎯 CMS Stock Screener V4.3B V1.5 — 候选池 + 持仓一体化")
st.caption("A负责每日选股；B用Master Watchlist保存候选与真实持仓。候选最多跟踪5个A扫描交易日；真实持仓不受5日限制，直到手动退出/止损/止盈。")

A_WORKSHEET = "V43A3_DailyCandidates"
B_LOG_WORKSHEET = "V43B_IntradayLog"
B_MASTER_WORKSHEET = "V43B_MasterWatchlist"
MARKET_TZ = ZoneInfo("America/New_York")
AUTO_REFRESH_MS = 15 * 60 * 1000
REMINDER_HOURS = {11, 13, 15}



def market_now():
    return datetime.now(MARKET_TZ)

def is_regular_market_hours(dt=None):
    dt = dt or market_now()
    if dt.weekday() >= 5:
        return False
    return time(9, 30) <= dt.time() <= time(16, 0)

def is_two_hour_reminder_window(dt=None):
    dt = dt or market_now()
    return is_regular_market_hours(dt) and dt.hour in REMINDER_HOURS

def safe_float(x, default=np.nan):
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default

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

@st.cache_data(ttl=120)
def get_intraday(ticker, interval, period):
    try:
        df = yf.download(ticker, interval=interval, period=period, auto_adjust=True,
                         progress=False, threads=False, prepost=False)
        return flatten_yf(df)
    except Exception:
        return None

def get_a_sheet():
    if gspread is None or Credentials is None:
        raise RuntimeError("requirements.txt需要gspread和google-auth。")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    client = gspread.authorize(creds)
    book = client.open(st.secrets["tracker"]["sheet_name"])
    return book.worksheet(A_WORKSHEET)


def get_or_create_b_log_sheet():
    """保存B每轮结果，用于识别上一轮状态变化。"""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=scopes
        )
        client = gspread.authorize(creds)
        book = client.open(st.secrets["tracker"]["sheet_name"])
        try:
            return book.worksheet(B_LOG_WORKSHEET)
        except Exception:
            return book.add_worksheet(title=B_LOG_WORKSHEET, rows=3000, cols=40)
    except Exception:
        return None


def get_or_create_b_master_sheet():
    """B主状态表：每只股票只保留一行最新状态。"""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=scopes
        )
        client = gspread.authorize(creds)
        book = client.open(st.secrets["tracker"]["sheet_name"])
        try:
            return book.worksheet(B_MASTER_WORKSHEET)
        except Exception:
            return book.add_worksheet(title=B_MASTER_WORKSHEET, rows=2000, cols=80)
    except Exception:
        return None

def load_b_master():
    ws = get_or_create_b_master_sheet()
    if ws is None:
        return pd.DataFrame()
    try:
        rec = ws.get_all_records()
        if not rec:
            return pd.DataFrame()
        df = pd.DataFrame(rec)
        if "Ticker" in df.columns:
            df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
        return df
    except Exception:
        return pd.DataFrame()

def save_b_master(df):
    """覆盖写入Master；Master是当前状态，不是15分钟日志。"""
    ws = get_or_create_b_master_sheet()
    if ws is None:
        return False
    try:
        x = df.copy() if df is not None else pd.DataFrame()
        x = x.replace([np.inf, -np.inf], np.nan).fillna("")
        ws.clear()
        if not x.empty:
            ws.update([list(x.columns)] + x.astype(str).values.tolist(), "A1")
        return True
    except Exception:
        return False

def sync_master_with_a(master, active_a):
    """
    A每天变化；Master不覆盖。
    - 最近5个A扫描日内候选 -> TRACKING
    - 不再处于5日窗口且未持仓 -> EXPIRED
    - 已持仓 -> HOLDING，永不因A名单变化而过期
    """
    now = market_now().strftime("%Y-%m-%d %H:%M:%S")
    m = master.copy() if master is not None else pd.DataFrame()
    if m.empty:
        m = pd.DataFrame(columns=["Ticker"])
    if "Ticker" not in m.columns:
        m["Ticker"] = ""
    m["Ticker"] = m["Ticker"].astype(str).str.strip().str.upper()

    # 先把未持仓旧候选标记为EXPIRED；随后活跃A候选会被重新激活。
    if "是否持仓" not in m.columns:
        m["是否持仓"] = "否"
    if "池状态" not in m.columns:
        m["池状态"] = "TRACKING"
    holding_mask = m["是否持仓"].astype(str).isin(["是","Y","YES","TRUE","1"])
    m.loc[holding_mask, "池状态"] = "HOLDING"
    m.loc[~holding_mask, "池状态"] = "EXPIRED"

    # 用Ticker做索引，方便更新/追加。
    rows = {str(r.get("Ticker","")).strip().upper(): r.to_dict() for _,r in m.iterrows() if str(r.get("Ticker","")).strip()}

    for _, arow in active_a.iterrows():
        t = str(arow.get("Ticker","")).strip().upper()
        if not t:
            continue
        old = rows.get(t, {})
        new = dict(old)
        # 保存A的最新字段，但不覆盖B的持仓管理字段。
        protected = {"首次进入B","是否持仓","实际买入日期","实际买入价","持仓止损","TP1","TP2","退出日期","退出价","退出原因"}
        for k,v in arow.to_dict().items():
            if k not in protected:
                new[k] = v
        new["Ticker"] = t
        if not old.get("首次进入B"):
            new["首次进入B"] = now
        new["最近同步A"] = now
        is_holding = str(old.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]
        new["是否持仓"] = "是" if is_holding else "否"
        new["池状态"] = "HOLDING" if is_holding else "TRACKING"
        rows[t] = new

    out = pd.DataFrame(list(rows.values())) if rows else pd.DataFrame(columns=["Ticker"])
    if not out.empty:
        out["Ticker"] = out["Ticker"].astype(str).str.upper()
        out = out.sort_values(["池状态","Ticker"], kind="stable").reset_index(drop=True)
    return out

def active_master_pool(master, max_candidates=20):
    """所有真实持仓都监控；非持仓候选最多取max_candidates只。"""
    if master is None or master.empty:
        return pd.DataFrame()
    x = master.copy()
    hold = x[x.get("池状态","").astype(str).eq("HOLDING")].copy() if "池状态" in x.columns else pd.DataFrame()
    watch = x[x.get("池状态","").astype(str).eq("TRACKING")].copy() if "池状态" in x.columns else pd.DataFrame()
    if "Rank" in watch.columns:
        watch["_rank"] = pd.to_numeric(watch["Rank"], errors="coerce")
        watch = watch.sort_values(["最近入选日期","_rank"], ascending=[False,True], na_position="last").drop(columns="_rank")
    watch = watch.head(max_candidates)
    return pd.concat([hold, watch], ignore_index=True, sort=False).drop_duplicates("Ticker", keep="first")

def mark_holding(master, ticker, entry, stop, tp1, tp2):
    x = master.copy()
    t = str(ticker).strip().upper()
    mask = x["Ticker"].astype(str).str.upper().eq(t)
    if not mask.any():
        return x
    now = market_now().strftime("%Y-%m-%d %H:%M:%S")
    x.loc[mask,"是否持仓"] = "是"
    x.loc[mask,"池状态"] = "HOLDING"
    x.loc[mask,"实际买入日期"] = now
    x.loc[mask,"实际买入价"] = float(entry) if entry else ""
    x.loc[mask,"持仓止损"] = float(stop) if stop else ""
    x.loc[mask,"TP1"] = float(tp1) if tp1 else ""
    x.loc[mask,"TP2"] = float(tp2) if tp2 else ""
    return x

def close_holding(master, ticker, exit_price=0.0, reason="手动SELL"):
    x = master.copy()
    t = str(ticker).strip().upper()
    mask = x["Ticker"].astype(str).str.upper().eq(t)
    if not mask.any():
        return x
    now = market_now().strftime("%Y-%m-%d %H:%M:%S")
    x.loc[mask,"是否持仓"] = "否"
    x.loc[mask,"池状态"] = "CLOSED"
    x.loc[mask,"退出日期"] = now
    x.loc[mask,"退出价"] = float(exit_price) if exit_price else ""
    x.loc[mask,"退出原因"] = reason
    return x

def load_previous_b_states():
    try:
        ws = get_or_create_b_log_sheet()
        if ws is None:
            return {}
        rec = ws.get_all_records()
        if not rec:
            return {}
        df = pd.DataFrame(rec)
        if "Ticker" not in df.columns or "盘中决策" not in df.columns:
            return {}
        if "检查时间" in df.columns:
            df["_dt"] = pd.to_datetime(df["检查时间"], errors="coerce")
            df = df.sort_values("_dt")
        latest = df.drop_duplicates("Ticker", keep="last")
        return dict(zip(
            latest["Ticker"].astype(str).str.upper(),
            latest["盘中决策"].astype(str)
        ))
    except Exception:
        return {}

def append_b_log(out, run_time):
    try:
        ws = get_or_create_b_log_sheet()
        if ws is None or out is None or out.empty:
            return False
        log = out.copy()
        log.insert(0, "检查时间", run_time.strftime("%Y-%m-%d %H:%M:%S"))
        log.insert(1, "检查日期", run_time.strftime("%Y-%m-%d"))
        log = log.replace([np.inf, -np.inf], np.nan).fillna("")
        existing = ws.get_all_values()
        if not existing:
            ws.update([list(log.columns)] + log.astype(str).values.tolist(), "A1")
        else:
            ws.append_rows(log.astype(str).values.tolist(), value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False

@st.cache_data(ttl=300)
def load_latest_a_candidates():
    ws = get_a_sheet()
    rec = ws.get_all_records()
    if not rec:
        return pd.DataFrame(), None
    df = pd.DataFrame(rec)
    if "Ticker" not in df.columns:
        raise RuntimeError("A候选表缺少Ticker列。")
    date_col = next((c for c in ["Scan Date","Date","日期"] if c in df.columns), None)
    if date_col is None:
        raise RuntimeError("A候选表缺少Scan Date，无法建立5交易日跟踪池。")
    df["_scan_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df[df["_scan_date"].notna()].copy()
    if df.empty:
        return pd.DataFrame(), None
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    scan_days = sorted(df["_scan_date"].drop_duplicates())
    latest_day = scan_days[-1]
    active_days = scan_days[-5:]
    active = df[df["_scan_date"].isin(active_days)].copy()
    last_dates = active.groupby("Ticker")["_scan_date"].max().to_dict()
    active = active.sort_values(["Ticker","_scan_date"]).drop_duplicates("Ticker", keep="last").copy()
    day_pos = {d:i for i,d in enumerate(scan_days)}
    active["最近入选日期"] = active["Ticker"].map(last_dates)
    active["跟踪天数"] = active["最近入选日期"].map(lambda d: day_pos[latest_day]-day_pos[d]+1)
    active["观察剩余天数"] = 6-active["跟踪天数"]
    active["池状态"] = "TRACKING"
    if "Rank" in active.columns:
        active["Rank"] = pd.to_numeric(active["Rank"], errors="coerce")
        active = active.sort_values(["最近入选日期","Rank"], ascending=[False,True])
    active["最近入选日期"] = pd.to_datetime(active["最近入选日期"]).dt.strftime("%Y-%m-%d")
    return active.reset_index(drop=True), latest_day.strftime("%Y-%m-%d")

def evaluate_1h(df):
    if df is None or len(df)<30:
        return {"valid":False,"status":"DATA","reason":"1H数据不足"}
    x=add_indicators(df)
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
    if df is None or len(df)<40:
        return {"valid":False,"reason":"15min数据不足"}
    x=add_indicators(df)
    r=x.iloc[-1]; prev=x.iloc[-2]; prev20=x.iloc[-21:-1]
    price=safe_float(r["Close"]); vwap=safe_float(r["VWAP"]); e9=safe_float(r["EMA9"]); e20=safe_float(r["EMA20"])
    rsi=safe_float(r["RSI14"]); atr=safe_float(r["ATR14"]); hist=safe_float(r["MACD_HIST"]); histp=safe_float(prev["MACD_HIST"])
    avgvol=safe_float(prev20["Volume"].mean()); volratio=safe_float(r["Volume"])/avgvol if avgvol>0 else np.nan
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
    return {
        "valid":True,"price":price,"vwap":vwap,"ema9":e9,"ema20":e20,"rsi":rsi,"atr":atr,
        "volratio":volratio,"breakout":breakout,"near":near,"above_vwap":above_vwap,
        "ema_structure":ema_structure,"macd_improving":macd_improving,"pullback":pullback,
        "overextended":overextended
    }

def analyze_holding(row):
    """真实持仓：不受5日候选池限制；检查止损/止盈/HOLD。"""
    ticker=str(row["Ticker"]).strip().upper()
    h1=evaluate_1h(get_intraday(ticker,"60m","3mo"))
    m15=evaluate_15m(get_intraday(ticker,"15m","10d"))
    price=safe_float(m15.get("price",np.nan))
    entry=safe_float(row.get("实际买入价",np.nan))
    stop=safe_float(row.get("持仓止损",np.nan))
    tp1=safe_float(row.get("TP1",np.nan))
    tp2=safe_float(row.get("TP2",np.nan))

    if pd.isna(price):
        d="⚪ DATA"; reason="持仓行情数据不足"
    elif not pd.isna(stop) and stop>0 and price<=stop:
        d="🛑 STOP LOSS"; reason=f"现价{price:.2f}已触及/跌破持仓止损{stop:.2f}"
    elif not pd.isna(tp2) and tp2>0 and price>=tp2:
        d="🟣 TAKE PROFIT TP2"; reason=f"现价{price:.2f}已达到TP2 {tp2:.2f}"
    elif not pd.isna(tp1) and tp1>0 and price>=tp1:
        d="🟠 TAKE PROFIT TP1"; reason=f"现价{price:.2f}已达到TP1 {tp1:.2f}"
    else:
        d="🟢 HOLD"; reason="持仓仍在止损与止盈区间内"

    pnl = ((price-entry)/entry*100) if (not pd.isna(price) and not pd.isna(entry) and entry>0) else np.nan
    return {
        "Ticker":ticker,"最近入选日期":row.get("最近入选日期",""),"跟踪天数":row.get("跟踪天数",""),"观察剩余天数":"持仓不受限",
        "池状态":"HOLDING","A排名":row.get("Rank",""),"A Early V2":row.get("Early V2 Score",""),
        "A信心":row.get("Confidence",row.get("信心等级","")),"A基本面":row.get("Fundamental Confirmation",row.get("基本面确认","")),
        "当前价格":price,"盘中决策":d,"决策依据":reason,"持仓成本":entry,"持仓盈亏%":pnl,
        "1H状态":h1.get("status","DATA"),"1H RSI":h1.get("rsi",np.nan),
        "15m VWAP":m15.get("vwap",np.nan),"15m EMA9":m15.get("ema9",np.nan),"15m EMA20":m15.get("ema20",np.nan),
        "15m RSI":m15.get("rsi",np.nan),"15m量比":m15.get("volratio",np.nan),
        "15m突破":"是" if m15.get("breakout") else "否","15m回踩":"是" if m15.get("pullback") else "否",
        "VWAP上方":"是" if m15.get("above_vwap") else "否","避免追高":"是" if m15.get("overextended") else "否",
        "参考入场":entry,"参考止损":stop,"TP1":tp1,"TP2":tp2
    }

def weak_fundamental(row):
    f=str(row.get("Fundamental Confirmation",row.get("基本面确认",""))).lower()
    c=str(row.get("Confidence",row.get("信心等级",""))).lower()
    return ("weak" in f) or ("弱" in f) or c in ["low","低"]

def decision(row,h1,m15):
    if not h1.get("valid"): return "⚪ DATA",h1.get("reason","1H数据不足"),np.nan,np.nan
    if not m15.get("valid"): return "⚪ DATA",m15.get("reason","15min数据不足"),np.nan,np.nan
    if h1["status"]=="弱": return "🔴 AVOID","1H趋势/动量未确认",np.nan,np.nan
    if m15["overextended"]: return "🟡 WAIT","偏离VWAP/EMA20过大或RSI过热，避免追高",np.nan,np.nan
    if not m15["above_vwap"]: return "🟡 WAIT","价格仍在VWAP下方",np.nan,np.nan
    if weak_fundamental(row): return "🟡 WAIT","A程序基本面/Confidence偏弱",np.nan,np.nan

    breakout_buy = h1["status"]=="强" and m15["breakout"] and m15["ema_structure"] and m15["macd_improving"] and not pd.isna(m15["volratio"]) and m15["volratio"]>=1.20
    pullback_buy = h1["status"] in ["强","中等"] and m15["pullback"] and m15["macd_improving"] and (pd.isna(m15["volratio"]) or m15["volratio"]>=0.80)

    if breakout_buy:
        stop=min(m15["vwap"],m15["ema20"])-0.35*m15["atr"]
        return "🟢 BUY","1H强势 + 15min放量突破 + VWAP上方 + 动量确认",m15["price"],stop
    if pullback_buy:
        stop=min(m15["vwap"],m15["ema20"])-0.35*m15["atr"]
        return "🟢 BUY","1H趋势保持 + 15min健康回踩 + 动量改善",m15["price"],stop
    if m15["near"] and m15["macd_improving"] and m15["above_vwap"]:
        return "🟠 EARLY BUY","接近15min突破位，动量改善且位于VWAP上方；等待正式突破/回踩确认",np.nan,np.nan
    return "🟡 WAIT","结构尚可，但15min触发条件未齐",np.nan,np.nan

def analyze_one(row):
    if str(row.get("池状态","")).upper() == "HOLDING" or str(row.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]:
        return analyze_holding(row)
    ticker=str(row["Ticker"]).strip().upper()
    h1=evaluate_1h(get_intraday(ticker,"60m","3mo"))
    m15=evaluate_15m(get_intraday(ticker,"15m","10d"))
    d,reason,entry,stop=decision(row,h1,m15)
    return {
        "Ticker":ticker,"最近入选日期":row.get("最近入选日期",""),"跟踪天数":row.get("跟踪天数",""),"观察剩余天数":row.get("观察剩余天数",""),"池状态":row.get("池状态","TRACKING"),"A排名":row.get("Rank",""),"A Early V2":row.get("Early V2 Score",""),
        "A信心":row.get("Confidence",row.get("信心等级","")),
        "A基本面":row.get("Fundamental Confirmation",row.get("基本面确认","")),
        "当前价格":m15.get("price",np.nan),"盘中决策":d,"决策依据":reason,
        "1H状态":h1.get("status","DATA"),"1H RSI":h1.get("rsi",np.nan),
        "15m VWAP":m15.get("vwap",np.nan),"15m EMA9":m15.get("ema9",np.nan),
        "15m EMA20":m15.get("ema20",np.nan),"15m RSI":m15.get("rsi",np.nan),
        "15m量比":m15.get("volratio",np.nan),"15m突破":"是" if m15.get("breakout") else "否",
        "15m回踩":"是" if m15.get("pullback") else "否","VWAP上方":"是" if m15.get("above_vwap") else "否",
        "避免追高":"是" if m15.get("overextended") else "否","参考入场":entry,"参考止损":stop
    }

with st.sidebar:
    st.header("V4.3B V1.5 参数")
    max_names=st.slider("最多监控B跟踪池股票",3,30,20,1)

    auto_monitor = st.toggle(
        "⏱️ 每15分钟自动检查",
        value=True,
        help="页面保持打开时，美股交易时段约每15分钟自动刷新并重新计算。"
    )

    two_hour_summary = st.toggle(
        "🔔 每2小时状态提醒",
        value=True,
        help="约11:30、13:30、15:30对应运行轮次显示汇总。"
    )

    st.caption("注意：Streamlit Cloud无人访问时不保证后台持续运行。")

    if st.button("🔄 清除数据缓存",use_container_width=True):
        st.cache_data.clear()
        st.success("缓存已清除")

if auto_monitor and st_autorefresh is not None:
    st_autorefresh(
        interval=AUTO_REFRESH_MS,
        limit=None,
        key="v43b_hourly_refresh"
    )
elif auto_monitor and st_autorefresh is None:
    st.warning("请在 requirements.txt 增加：streamlit-autorefresh")

st.info("流程：1H判断大方向 → 15min找突破/回踩 → VWAP过滤 → 防追高 → BUY / WAIT / AVOID。")

try:
    a_df,scan_date=load_latest_a_candidates()
except Exception as e:
    st.error(f"读取A候选失败：{e}")
    st.stop()

if a_df.empty:
    st.warning("A候选为空，请先盘后运行V4.3A.3。")
    st.stop()

# 关键变化：A只负责提供最近5个扫描日候选；B Master负责长期保存当前状态。
master_df = load_b_master()
master_df = sync_master_with_a(master_df, a_df)
save_b_master(master_df)
monitor_df = active_master_pool(master_df, max_candidates=max_names)

st.success(
    f"A基准日：{scan_date} ｜ B当前监控{len(monitor_df)}只 "
    f"（候选{int((monitor_df.get('池状态','')=='TRACKING').sum()) if not monitor_df.empty else 0}，"
    f"持仓{int((monitor_df.get('池状态','')=='HOLDING').sum()) if not monitor_df.empty else 0}）。"
)

preview=[c for c in ["Ticker","池状态","是否持仓","首次进入B","最近入选日期","跟踪天数","观察剩余天数","Rank","Company","Early V2 Score","Confidence","Fundamental Confirmation"] if c in monitor_df.columns]
if preview and not monitor_df.empty:
    st.dataframe(monitor_df[preview],hide_index=True,use_container_width=True)

with st.expander("💼 持仓管理（只有实际买入后才标记）", expanded=False):
    st.caption("B出现BUY只是程序买点信号，不代表你已经买入。只有你实际成交后，才在这里标记为持仓；标记后不受5日候选期限限制。")
    choices = master_df.loc[master_df["池状态"].isin(["TRACKING","HOLDING"]),"Ticker"].astype(str).tolist() if not master_df.empty else []
    if choices:
        pos_ticker = st.selectbox("股票", choices, key="pos_ticker")
        selected = master_df[master_df["Ticker"].astype(str).eq(pos_ticker)].iloc[-1]
        default_entry = safe_float(selected.get("实际买入价", selected.get("参考入场",0)), 0.0)
        default_stop = safe_float(selected.get("持仓止损", selected.get("参考止损",0)), 0.0)
        default_tp1 = safe_float(selected.get("TP1",0), 0.0)
        default_tp2 = safe_float(selected.get("TP2",0), 0.0)
        c1,c2,c3,c4 = st.columns(4)
        actual_entry = c1.number_input("实际买入价", min_value=0.0, value=float(default_entry if not pd.isna(default_entry) else 0.0), step=0.01)
        actual_stop = c2.number_input("持仓止损", min_value=0.0, value=float(default_stop if not pd.isna(default_stop) else 0.0), step=0.01)
        actual_tp1 = c3.number_input("TP1", min_value=0.0, value=float(default_tp1 if not pd.isna(default_tp1) else 0.0), step=0.01)
        actual_tp2 = c4.number_input("TP2", min_value=0.0, value=float(default_tp2 if not pd.isna(default_tp2) else 0.0), step=0.01)
        b1,b2 = st.columns(2)
        if b1.button("✅ 标记为已买入 / 加入持仓", use_container_width=True):
            master_df = mark_holding(master_df, pos_ticker, actual_entry, actual_stop, actual_tp1, actual_tp2)
            save_b_master(master_df)
            st.success(f"{pos_ticker} 已进入真实持仓池；以后即使不在A名单，也会继续跟踪。")
            st.rerun()
        exit_price = st.number_input("退出价（准备退出时填写，可留0）", min_value=0.0, value=0.0, step=0.01)
        if b2.button("🏁 标记为已卖出 / 结束跟踪", use_container_width=True):
            master_df = close_holding(master_df, pos_ticker, exit_price, "手动SELL")
            save_b_master(master_df)
            st.success(f"{pos_ticker} 已标记为CLOSED，历史仍保留在Master和Log。")
            st.rerun()
    else:
        st.info("当前没有可管理的候选或持仓。")

# 后续监控统一使用B Master，而不是直接使用当天A名单。
a_df = monitor_df.copy()

def run_b_monitor(a_df, trigger="手动检查"):
    if a_df is None or a_df.empty:
        st.warning("当前没有需要监控的股票。")
        return
    rows=[]
    progress=st.progress(0)
    status=st.empty()
    previous_states=load_previous_b_states()

    for i,(_,row) in enumerate(a_df.iterrows(),1):
        status.write(f"正在分析 {row['Ticker']} ({i}/{len(a_df)})")
        rows.append(analyze_one(row))
        progress.progress(int(i/len(a_df)*100))

    status.empty()
    progress.empty()

    out=pd.DataFrame(rows)
    out["上一轮状态"] = out["Ticker"].map(previous_states).fillna("首次检查")

    out["状态变化"] = out.apply(
        lambda r: (
            f"{r['上一轮状态']} → {r['盘中决策']}"
            if r["上一轮状态"] != "首次检查"
            and r["上一轮状态"] != r["盘中决策"]
            else ("首次检查" if r["上一轮状态"] == "首次检查" else "无变化")
        ),
        axis=1
    )

    out["新BUY提醒"] = out.apply(
        lambda r: (
            "🔔 新BUY"
            if r["盘中决策"] == "🟢 BUY"
            and r["上一轮状态"] != "🟢 BUY"
            else ""
        ),
        axis=1
    )

    order={"🛑 STOP LOSS":0,"🟣 TAKE PROFIT TP2":1,"🟠 TAKE PROFIT TP1":2,"🟢 BUY":3,"🟠 EARLY BUY":4,"🟢 HOLD":5,"🟡 WAIT":6,"🔴 AVOID":7,"⚪ DATA":8}
    out["_o"]=out["盘中决策"].map(order).fillna(9)

    sort_cols=["_o"]
    if "A排名" in out.columns:
        sort_cols.append("A排名")

    out=out.sort_values(sort_cols).drop(columns="_o").reset_index(drop=True)

    now=market_now()
    append_b_log(out, now)

    # 把本轮最新价格/决策写回Master，但不把Log变成Master。
    global master_df
    if master_df is not None and not master_df.empty:
        mm = master_df.copy()
        for _, rr in out.iterrows():
            mask = mm["Ticker"].astype(str).str.upper().eq(str(rr["Ticker"]).upper())
            if not mask.any():
                continue
            mm.loc[mask,"最后检查时间"] = now.strftime("%Y-%m-%d %H:%M:%S")
            mm.loc[mask,"最后价格"] = rr.get("当前价格","")
            mm.loc[mask,"最后决策"] = rr.get("盘中决策","")
            mm.loc[mask,"最后决策依据"] = rr.get("决策依据","")
            # 对未持仓候选，只保存B给出的参考入场/止损。真实持仓字段不自动覆盖。
            is_hold = mm.loc[mask,"是否持仓"].astype(str).isin(["是","Y","YES","TRUE","1"]).any() if "是否持仓" in mm.columns else False
            if not is_hold:
                if not pd.isna(safe_float(rr.get("参考入场",np.nan))):
                    mm.loc[mask,"参考入场"] = rr.get("参考入场","")
                if not pd.isna(safe_float(rr.get("参考止损",np.nan))):
                    mm.loc[mask,"参考止损"] = rr.get("参考止损","")
        master_df = mm
        save_b_master(master_df)

    st.session_state["v43b_result"]=out
    st.session_state["v43b_time"]=now.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["v43b_trigger"]=trigger
    minute_bucket = (now.minute // 15) * 15
    st.session_state["v43b_last_15m"] = now.strftime("%Y-%m-%d-%H") + f"-{minute_bucket:02d}"

if a_df.empty:
    st.warning("当前B Master没有需要监控的候选或持仓。")

manual_run = st.button(
    "🎯 立即运行V4.3B盘中确认",
    type="primary",
    use_container_width=True
)

now = market_now()
minute_bucket = (now.minute // 15) * 15
bucket_key = now.strftime("%Y-%m-%d-%H") + f"-{minute_bucket:02d}"

first_open = (
    auto_monitor
    and is_regular_market_hours(now)
    and "v43b_result" not in st.session_state
)

new_15m_bucket = (
    auto_monitor
    and is_regular_market_hours(now)
    and st.session_state.get("v43b_last_15m") != bucket_key
)

if manual_run:
    run_b_monitor(a_df, trigger="手动检查")
elif first_open or new_15m_bucket:
    run_b_monitor(a_df, trigger="每15分钟自动检查")

if "v43b_result" in st.session_state:
    out=st.session_state["v43b_result"]
    st.subheader("📡 V4.3B盘中确认结果")
    st.caption(
        f"最近运行：{st.session_state.get('v43b_time','')} ｜ "
        f"触发方式：{st.session_state.get('v43b_trigger','')}"
    )

    if "新BUY提醒" in out.columns:
        new_buy = out[out["新BUY提醒"] == "🔔 新BUY"]
        if not new_buy.empty:
            st.success(
                "🚨 BUY到点提醒：" +
                "、".join(new_buy["Ticker"].astype(str).tolist())
            )

    if "状态变化" in out.columns:
        changed = out[~out["状态变化"].isin(["无变化","首次检查"])]
        if not changed.empty:
            st.warning(
                "⚠️ 本轮状态变化：" +
                "；".join(
                    changed.apply(
                        lambda r: f"{r['Ticker']} {r['状态变化']}",
                        axis=1
                    ).tolist()
                )
            )

    if two_hour_summary and is_two_hour_reminder_window():
        buys = out.loc[out["盘中决策"]=="🟢 BUY","Ticker"].astype(str).tolist()
        early = out.loc[out["盘中决策"]=="🟠 EARLY BUY","Ticker"].astype(str).tolist()
        holds = out.loc[out["盘中决策"]=="🟢 HOLD","Ticker"].astype(str).tolist()
        actions = out.loc[out["盘中决策"].isin(["🛑 STOP LOSS","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"]),"Ticker"].astype(str).tolist()
        waits = out.loc[out["盘中决策"]=="🟡 WAIT","Ticker"].astype(str).tolist()
        avoids = out.loc[out["盘中决策"]=="🔴 AVOID","Ticker"].astype(str).tolist()
        text = f"🔔 两小时状态提醒｜BUY {len(buys)} ｜ EARLY {len(early)} ｜ HOLD {len(holds)} ｜ TP/STOP {len(actions)}"
        if buys:
            text += " ｜ BUY：" + ", ".join(buys)
        if actions:
            text += " ｜ 需处理：" + ", ".join(actions)
        text += f" ｜ WAIT {len(waits)} ｜ AVOID {len(avoids)}"
        st.info(text)
    fmt={"当前价格":"{:.2f}","持仓成本":"{:.2f}","持仓盈亏%":"{:.2f}","1H RSI":"{:.1f}","15m VWAP":"{:.2f}","15m EMA9":"{:.2f}","15m EMA20":"{:.2f}","15m RSI":"{:.1f}","15m量比":"{:.2f}","参考入场":"{:.2f}","参考止损":"{:.2f}","TP1":"{:.2f}","TP2":"{:.2f}"}
    st.dataframe(out.style.format(fmt,na_rep=""),hide_index=True,use_container_width=True)

    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric("🟢 BUY",int((out["盘中决策"]=="🟢 BUY").sum()))
    c2.metric("🟠 EARLY",int((out["盘中决策"]=="🟠 EARLY BUY").sum()))
    c3.metric("🟢 HOLD",int((out["盘中决策"]=="🟢 HOLD").sum()))
    c4.metric("🟡 WAIT",int((out["盘中决策"]=="🟡 WAIT").sum()))
    c5.metric("🛑 TP/STOP",int(out["盘中决策"].isin(["🛑 STOP LOSS","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"]).sum()))

    csv=out.to_csv(index=False).encode("utf-8-sig")
    st.download_button("💾 下载盘中结果",csv,
        file_name=f"V43B_Intraday_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv",
        mime="text/csv",use_container_width=True)

with st.expander("查看V4.3B V1.5规则"):
    st.markdown("""
**B不重新选股，也没有第二套100分。**

**自动监控：**
- 页面打开期间，美股交易时段约每15分钟自动刷新并重新检查。
- 每次15分钟检查一旦发现 WAIT → BUY / 新BUY，会立即在页面顶部提示。
- 约每2小时显示一次状态汇总。
- 每轮结果保存到 `V43B_IntradayLog`，用于识别上一轮状态。
- 手动“立即运行”按钮保留。

**5交易日退出机制：** 未买入候选从最近一次A入选起最多跟踪5个A扫描交易日；期间再次被A选中则重新计时；明显1H破坏可提前AVOID；超过5日后自动从滚动池消失。真实BUY后不应按5日退出，而应转入持仓/C程序持续跟踪，直到SELL / STOP / TAKE PROFIT。

- 1H：EMA20/EMA50、MACD、RSI确认大方向。
- 15min：VWAP、EMA9/EMA20、MACD、RSI、成交量、突破和回踩。
- 突破BUY：1H强 + 15min突破 + 量比≥1.20 + VWAP上方。
- 回踩BUY：1H趋势保持 + 15min回踩VWAP/EMA后企稳。
- WAIT：VWAP下方、接近突破但未确认、基本面弱、或明显追高。
- AVOID：1H趋势/动量已经破坏。
""")
