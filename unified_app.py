
import streamlit as st
import pandas as pd
import numpy as np
import re
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, time
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


# ============================================================
# CMS UNIFIED APP V1.9 DARK TERMINAL
# 统一产品化界面：不修改 A / B / C 核心交易逻辑，不写入 Google Sheet。
# 数据来源：
#   A_Candidates
#   B_MasterList
#   B_Log
# ============================================================

st.set_page_config(
    page_title="CMS Unified App",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

NY = ZoneInfo("America/New_York")
A_WORKSHEET = "A_Candidates"
B_MASTER_WORKSHEET = "B_MasterList"
B_LOG_WORKSHEET = "B_Log"

# ---------- UI ----------
st.markdown("""
<style>
:root {
    --cms-bg: #0b2a4a;
    --cms-bg2: #0f365d;
    --cms-panel: #123c65;
    --cms-panel2: #174a79;
    --cms-border: rgba(120, 190, 255, 0.28);
    --cms-border-strong: rgba(49, 145, 255, 0.72);
    --cms-text: #e8f2ff;
    --cms-muted: #aac6e4;
    --cms-blue: #1f8fff;
    --cms-green: #26d7a1;
    --cms-yellow: #f6c84c;
    --cms-red: #ff5d6c;
    --cms-purple: #9c86ff;
}

html, body, [class*="css"] {font-size: 14px;}

/* Remove Streamlit top chrome / white frame */
header[data-testid="stHeader"] {
    height: 0 !important;
    min-height: 0 !important;
    background: transparent !important;
    border: none !important;
}
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
#MainMenu {
    display: none !important;
}
.stApp > header {background: transparent !important;}

.stApp {
    background:
      radial-gradient(circle at 15% 0%, rgba(43,142,232,.22), transparent 25%),
      radial-gradient(circle at 95% 12%, rgba(43,126,205,.16), transparent 24%),
      linear-gradient(180deg, #124878 0%, #0c3154 42%, var(--cms-bg) 100%);
    color: var(--cms-text);
}
.block-container {padding-top: .30rem; padding-bottom: 1.4rem; max-width: 1680px;}

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d3760 0%, #0b2d4f 58%, #082440 100%);
    border-right: 1px solid rgba(88,145,204,.20);
}
[data-testid="stSidebar"] * {color: #d8e8fa;}
[data-testid="stSidebar"] hr {border-color: rgba(122,167,214,.18);}
[data-testid="stSidebar"] [role="radiogroup"] label {
    padding: .35rem .5rem; border-radius: 9px; margin-bottom: .05rem;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {background: rgba(31,143,255,.10);}

/* Main text */
h1,h2,h3,h4,h5,h6, p, label {color: var(--cms-text);}
[data-testid="stCaptionContainer"] {color: var(--cms-muted);}
.cms-title {font-weight: 850; font-size: 1.65rem; line-height: 1.1; margin-bottom: 0;}
.cms-subtitle {color: var(--cms-muted); font-size: .88rem; margin-top: .2rem; margin-bottom: .55rem;}

/* Metrics */
[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(23,73,119,.96), rgba(15,52,87,.96));
    border: 1px solid var(--cms-border);
    padding: 10px 12px;
    border-radius: 10px;
    min-height: 80px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.02);
}
[data-testid="stMetricLabel"] {font-size: .76rem !important; color: #a9bed5 !important;}
[data-testid="stMetricValue"] {font-size: 1.30rem !important; line-height: 1.15 !important; color: #eef6ff !important;}
[data-testid="stMetricDelta"] {font-size: .74rem !important;}

/* General controls */
[data-baseweb="select"] > div, [data-testid="stSelectbox"] > div > div {
    background: #123d68 !important; border-color: rgba(105,158,211,.22) !important;
}
.stButton > button {
    border-radius: 9px; border: 1px solid rgba(95,153,213,.25);
    background: #123e69; color: #eef7ff;
}
.stButton > button:hover {border-color: #1f8fff; color: white; background: #175486;}

/* Dataframes */
[data-testid="stDataFrame"] {border: 1px solid var(--cms-border); border-radius: 10px; overflow: hidden;}

/* Summary cards */
div[class*="st-key-summary_card_"] button {
    min-height: 118px !important; width: 100% !important; border-radius: 10px !important;
    border: 1px solid var(--cms-border) !important;
    background: linear-gradient(145deg,#164a79,#10395f) !important;
    justify-content: flex-start !important; text-align: left !important; padding: 10px 12px !important;
}
div[class*="st-key-summary_card_"] button:hover {border-color: var(--cms-border-strong) !important; background:#1a5689 !important;}
div[class*="st-key-summary_card_"] button p {
    white-space: pre-line !important; line-height: 1.22 !important; text-align:left !important; width:100% !important;
    font-size:.78rem !important; font-weight:650 !important;
}

/* Opportunity cards */
div[class*="st-key-opportunity_card_"] button {
    min-height: 116px !important; width:100% !important; border-radius: 12px !important;
    border:1px solid var(--cms-border) !important; border-left:3px solid rgba(111,164,219,.28) !important;
    background: linear-gradient(145deg,#174d7e 0%,#103b64 100%) !important;
    justify-content:flex-start !important; text-align:left !important; padding:11px 13px !important;
    margin-bottom:7px !important; box-shadow:0 6px 18px rgba(0,0,0,.10) !important;
    transition: all .14s ease !important;
}
div[class*="st-key-opportunity_card_"] button:hover {
    border-color:#278fff !important; border-left-color:#27a0ff !important; background:#1b5b91 !important;
    transform: translateY(-1px); box-shadow:0 8px 22px rgba(0,0,0,.18) !important;
}
div[class*="st-key-opportunity_card_"] button p {
    white-space:pre-line !important; line-height:1.34 !important; text-align:left !important; width:100% !important;
    font-size:.82rem !important; color:#e4effb !important;
}

.cms-detail-head {
    border: 1px solid var(--cms-border); border-radius: 12px; padding: 14px 16px;
    background: linear-gradient(145deg,#174d7d,#10385f); margin: 0 0 10px 0;
    box-shadow: 0 6px 20px rgba(0,0,0,.10);
}
.cms-detail-ticker {font-size: 1.36rem; font-weight: 850; letter-spacing:-.02em; color:#f2f7ff;}
.cms-detail-company {color:#8fa9c5; font-size:.80rem; margin-top:2px;}
.cms-section-label {font-size:.70rem; color:#6f93b9; text-transform:uppercase; letter-spacing:.11em; margin-bottom:2px;}
.cms-reason {
    border-left: 3px solid #1f8fff; padding: 8px 11px; background: rgba(42,157,255,.13);
    color:#cfe2f6; border-radius:0 8px 8px 0; margin: 5px 0 8px 0; font-size:.80rem;
}

/* Radio pills */
[data-testid="stRadio"] label {font-size:.80rem !important;}

/* Plotly wrapper */
[data-testid="stPlotlyChart"] {
    border:1px solid var(--cms-border); border-radius:12px; background:#0e355b; padding:4px;
}

/* Reduce excessive whitespace */
hr {margin:.6rem 0 !important; border-color:rgba(110,160,210,.16) !important;}
.element-container {margin-bottom:.22rem;}
</style>
""", unsafe_allow_html=True)


# ---------- helpers ----------
def market_now():
    return datetime.now(NY)

def market_open(dt=None):
    dt = dt or market_now()
    return dt.weekday() < 5 and time(9, 30) <= dt.time() <= time(16, 0)

def sfloat(x, default=np.nan):
    try:
        if x is None or pd.isna(x):
            return default
        s = str(x).strip().replace(",", "").replace("$", "").replace("%", "")
        if s == "" or s.lower() in {"nan", "none", "n/a", "na"}:
            return default
        return float(s)
    except Exception:
        return default

def pct_text(x):
    v = sfloat(x, np.nan)
    if pd.isna(v):
        return "—"
    # Sheet may store 0.034 or 3.4; display safely
    if abs(v) <= 1.5:
        v *= 100
    return f"{v:+.1f}%"

def money_text(x):
    v = sfloat(x, np.nan)
    if pd.isna(v):
        return "—"
    return f"${v:,.2f}"

def truthy(x):
    return str(x).strip().lower() in {
        "是","yes","y","true","1","holding","持仓","已持仓"
    }

def first_existing(df, names, default=None):
    if df is None or df.empty:
        return default
    for c in names:
        if c in df.columns:
            return c
    return default

COLUMN_ALIASES = {
    "股票代码": "Ticker",
    "代码": "Ticker",
    "公司": "Company",
    "扫描日期": "Scan Date",
    "扫描时间": "Scan Time",
    "结果": "A5决策",
    "排名": "Rank",
    "信心等级": "Confidence",
    "空间等级": "空间等级",
    "空间优先级": "空间优先级",
    "上方空间": "上方空间",
}

def normalize(df):
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    x = x.rename(columns={c: COLUMN_ALIASES.get(c, c) for c in x.columns})
    if "Ticker" in x.columns:
        x["Ticker"] = x["Ticker"].astype(str).str.strip().str.upper()
    return x


def latest_master_snapshot(master):
    """Keep one newest B_MasterList row per ticker."""
    if master is None or master.empty or "Ticker" not in master.columns:
        return pd.DataFrame()

    x = master.copy()
    x["Ticker"] = x["Ticker"].astype(str).str.strip().str.upper()
    tcol = first_existing(
        x, ["最后检查时间", "检查时间", "更新时间", "Timestamp", "时间", "扫描时间"]
    )
    x["_seq"] = np.arange(len(x))
    if tcol:
        x["_ts"] = pd.to_datetime(x[tcol], errors="coerce")
        x = x.sort_values(["Ticker", "_ts", "_seq"], na_position="first")
    else:
        x = x.sort_values(["Ticker", "_seq"])
    x = x.drop_duplicates("Ticker", keep="last")
    return x.drop(columns=["_ts", "_seq"], errors="ignore").reset_index(drop=True)


def _calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _calc_atr(df, period=14):
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_buy_reference(df15):
    """
    Reference-only visualization of B v1.8 location conditions.
    Does NOT create or override BUY signals.
    """
    out = {
        "valid": False,
        "price": np.nan, "vwap": np.nan, "ema9": np.nan, "ema20": np.nan,
        "atr": np.nan, "rsi": np.nan, "pullback_low": np.nan,
        "pullback_high": np.nan, "breakout": np.nan,
        "dist_pullback_pct": np.nan, "dist_breakout_pct": np.nan,
        "setup_type": "—",
    }
    if df15 is None or df15.empty or len(df15) < 40:
        return out

    x = df15.copy()
    for c in ["Open","High","Low","Close","Volume"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["Open","High","Low","Close","Volume"])
    if len(x) < 40:
        return out

    x["EMA9"] = x["Close"].ewm(span=9, adjust=False).mean()
    x["EMA20"] = x["Close"].ewm(span=20, adjust=False).mean()
    x["RSI14"] = _calc_rsi(x["Close"], 14)
    x["ATR14"] = _calc_atr(x, 14)

    typical = (x["High"] + x["Low"] + x["Close"]) / 3
    session = pd.Series(x.index.date, index=x.index)
    x["VWAP"] = (
        (typical * x["Volume"]).groupby(session).cumsum()
        / x["Volume"].groupby(session).cumsum().replace(0, np.nan)
    )

    r = x.iloc[-1]
    price = sfloat(r["Close"], np.nan)
    vwap = sfloat(r["VWAP"], np.nan)
    ema9 = sfloat(r["EMA9"], np.nan)
    ema20 = sfloat(r["EMA20"], np.nan)
    atr = sfloat(r["ATR14"], np.nan)
    rsi = sfloat(r["RSI14"], np.nan)
    breakout = sfloat(x["High"].iloc[-21:-1].max(), np.nan)

    if any(pd.isna(v) for v in [price, vwap, ema9, ema20, atr]) or atr <= 0:
        return out

    base = max(vwap, ema20)
    pullback_low = max(base, ema9 - 0.40 * atr)
    pullback_high = max(pullback_low, ema9 + 0.40 * atr)

    if pullback_low <= price <= pullback_high:
        dist_pull = 0.0
    elif price > pullback_high:
        dist_pull = (price - pullback_high) / pullback_high
    else:
        dist_pull = (price - pullback_low) / pullback_low

    dist_break = (
        (breakout - price) / price
        if not pd.isna(breakout) and price > 0
        else np.nan
    )

    if pullback_low <= price <= pullback_high:
        setup = "回踩关注区内"
    elif not pd.isna(dist_break) and -0.008 <= dist_break <= 0.012:
        setup = "接近突破触发位"
    elif price > pullback_high:
        setup = "等待回踩 / 避免追高"
    else:
        setup = "等待重新站回结构"

    out.update({
        "valid": True, "price": price, "vwap": vwap, "ema9": ema9,
        "ema20": ema20, "atr": atr, "rsi": rsi,
        "pullback_low": pullback_low, "pullback_high": pullback_high,
        "breakout": breakout, "dist_pullback_pct": dist_pull,
        "dist_breakout_pct": dist_break, "setup_type": setup,
    })
    return out


def buy_reference_text(ref):
    if not ref or not ref.get("valid"):
        return "—"
    return f"${ref['pullback_low']:.2f}–${ref['pullback_high']:.2f}"


def distance_text(v):
    x = sfloat(v, np.nan)
    if pd.isna(x):
        return "—"
    if abs(x) < 0.0005:
        return "区域内"
    return f"{x:+.1%}"


def get_book():
    if gspread is None or Credentials is None:
        raise RuntimeError("requirements.txt 需要 gspread 和 google-auth")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open(st.secrets["tracker"]["sheet_name"])

@st.cache_data(ttl=15, show_spinner=False)
def load_sheet(sheet_name):
    book = get_book()
    ws = book.worksheet(sheet_name)
    rows = ws.get_all_records()
    return normalize(pd.DataFrame(rows))

@st.cache_data(ttl=45, show_spinner=False)
def load_price_history(ticker, period="3mo", interval="1d"):
    """Yahoo chart helper only. B/C decisions still come from B_MasterList."""
    if not ticker:
        return pd.DataFrame()
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
            prepost=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        need = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in need):
            return pd.DataFrame()

        df = df[need].copy()
        for c in need:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["Open", "High", "Low", "Close"])
    except Exception:
        return pd.DataFrame()

def latest_a_buys(a):
    if a is None or a.empty or "Ticker" not in a.columns:
        return pd.DataFrame()
    x = a.copy()

    date_col = first_existing(x, ["Scan Date", "Date", "日期"])
    if date_col:
        d = pd.to_datetime(x[date_col], errors="coerce")
        if d.notna().any():
            x = x[d.dt.date == d.max().date()].copy()

    decision_col = first_existing(x, ["A5决策", "决策", "结果"])
    if decision_col:
        keep = x[decision_col].astype(str).str.strip().isin(["买", "BUY", "Buy", "buy"])
        x = x[keep].copy()

    rank_col = first_existing(x, ["Rank", "排名"])
    if rank_col:
        x["_rank"] = pd.to_numeric(x[rank_col], errors="coerce").fillna(9999)
        x = x.sort_values("_rank")

    return x.drop(columns=["_rank"], errors="ignore")

def active_master(master):
    if master is None or master.empty:
        return pd.DataFrame()
    x = master.copy()
    if "池状态" in x.columns:
        dead = x["池状态"].astype(str).str.contains("STOP|退出|EXPIRED|失效", case=False, regex=True)
        x = x[~dead].copy()
    return x

def holdings(master):
    if master is None or master.empty:
        return pd.DataFrame()
    if "是否持仓" not in master.columns:
        return pd.DataFrame(columns=master.columns)
    return master[master["是否持仓"].map(truthy)].copy()

def decision_counts(master):
    if master is None or master.empty:
        return {}
    c = first_existing(master, ["最后决策", "B决策", "决策"])
    if not c:
        return {}
    vals = master[c].astype(str)

    buy_mask = (
        vals.str.contains("BUY", case=False, na=False)
        & ~vals.str.contains("EARLY", case=False, na=False)
    )

    return {
        "BUY": int(buy_mask.sum()),
        "EARLY": int(vals.str.contains("EARLY", case=False, na=False).sum()),
        "WAIT": int(vals.str.contains("WAIT", case=False, na=False).sum()),
        "AVOID": int(vals.str.contains("AVOID", case=False, na=False).sum()),
    }

def alert_today_count(log):
    if log is None or log.empty:
        return 0
    date_col = first_existing(log, ["检查时间", "时间", "Timestamp", "DateTime", "扫描时间"])
    if not date_col:
        return len(log)
    d = pd.to_datetime(log[date_col], errors="coerce")
    return int((d.dt.date == market_now().date()).sum())

def opportunity_sort_value(row):
    dec = str(row.get("最后决策", row.get("B决策", ""))).upper()
    if "BUY" in dec and "EARLY" not in dec:
        base = 0
    elif "EARLY" in dec:
        base = 1
    elif "WAIT" in dec:
        base = 2
    else:
        base = 3

    room = str(row.get("空间等级", ""))
    if "🔥" in room or "强" in room:
        room_adj = 0
    elif "✅" in room or "好" in room:
        room_adj = 0.1
    elif "开放" in room or "🌤" in room:
        room_adj = 0.2
    else:
        room_adj = 0.4
    return base + room_adj

def compact_opportunity_table(master):
    if master is None or master.empty:
        return pd.DataFrame()
    x = active_master(master).copy()
    if x.empty:
        return x
    x["_sort"] = x.apply(opportunity_sort_value, axis=1)
    x = x.sort_values(["_sort"], ascending=True)

    wanted = [
        "Ticker","Company","最后决策","最后价格","空间等级","上方空间",
        "Rank","共振数","1H状态","15m RSI","15m量比","参考入场",
        "参考止损","TP1","TP2","最后决策依据"
    ]
    cols = [c for c in wanted if c in x.columns]
    return x[cols].drop(columns=["_sort"], errors="ignore")

def compact_position_table(pos):
    if pos is None or pos.empty:
        return pd.DataFrame()
    wanted = [
        "Ticker","Company","C阶段","最后价格","实际买入价","最高浮盈%",
        "动态保护价","持仓止损","TP1","TP2","利润回吐%","最后决策","最后决策依据"
    ]
    cols = [c for c in wanted if c in pos.columns]
    return pos[cols].copy()

def latest_alerts(log, n=40):
    if log is None or log.empty:
        return pd.DataFrame()
    x = log.copy()
    date_col = first_existing(x, ["检查时间", "时间", "Timestamp", "DateTime", "扫描时间"])
    if date_col:
        x["_dt"] = pd.to_datetime(x[date_col], errors="coerce")
        x = x.sort_values("_dt", ascending=False)
    wanted = [
        date_col, "Ticker","Company","决策","最后决策","B决策",
        "价格","最后价格","1H状态","15m RSI","15m量比","决策依据","最后决策依据"
    ]
    cols = []
    for c in wanted:
        if c and c in x.columns and c not in cols:
            cols.append(c)
    return x[cols].head(n).drop(columns=["_dt"], errors="ignore")

def union_tickers(*dfs):
    vals = []
    for df in dfs:
        if df is not None and not df.empty and "Ticker" in df.columns:
            vals += df["Ticker"].dropna().astype(str).str.upper().tolist()
    return sorted(set([x for x in vals if x and x not in {"NAN","NONE"}]))

def ticker_row(ticker, master, a):
    for df in [master, a]:
        if df is not None and not df.empty and "Ticker" in df.columns:
            hit = df[df["Ticker"].astype(str).str.upper() == ticker.upper()]
            if not hit.empty:
                return hit.iloc[-1]
    return pd.Series(dtype=object)

def status_badge(dec):
    s = str(dec)
    if "EARLY" in s.upper():
        return "🟡 EARLY"
    if "BUY" in s.upper():
        return "🟢 BUY"
    if "WAIT" in s.upper():
        return "⚪ WAIT"
    if "AVOID" in s.upper():
        return "🔴 AVOID"
    if "HOLD" in s.upper():
        return "🔵 HOLD"
    return s if s else "—"




def level_value(row, names):
    for name in names:
        if name in row.index:
            v = sfloat(row.get(name, np.nan), np.nan)
            if not pd.isna(v):
                return v
    return np.nan

def range_bounds(value):
    if value is None:
        return (np.nan, np.nan)
    s = str(value).strip().replace("$", "").replace(",", "")
    nums = re.findall(r"-?\d+(?:\.\d+)?", s)
    if not nums:
        return (np.nan, np.nan)
    vals = [float(x) for x in nums[:2]]
    if len(vals) == 1:
        return (vals[0], vals[0])
    return (min(vals), max(vals))

def latest_row_for_ticker(ticker, master, a):
    """
    优先读取该股票最新 B_MasterList 记录；没有时才回退到 A。
    这样右侧价格、B决策、1H、15m、Stop、TP1/TP2来自同一只股票。
    """
    if master is not None and not master.empty and "Ticker" in master.columns:
        hit = master[master["Ticker"].astype(str).str.upper() == ticker.upper()].copy()
        if not hit.empty:
            tcol = first_existing(hit, ["最后检查时间", "检查时间", "更新时间", "Timestamp", "时间"])
            if tcol:
                hit["_ts"] = pd.to_datetime(hit[tcol], errors="coerce")
                if hit["_ts"].notna().any():
                    hit = hit.sort_values("_ts")
            return hit.iloc[-1]

    if a is not None and not a.empty and "Ticker" in a.columns:
        hit = a[a["Ticker"].astype(str).str.upper() == ticker.upper()].copy()
        if not hit.empty:
            dcol = first_existing(hit, ["Scan Date", "Date", "日期"])
            if dcol:
                hit["_d"] = pd.to_datetime(hit[dcol], errors="coerce")
                if hit["_d"].notna().any():
                    hit = hit.sort_values("_d")
            return hit.iloc[-1]

    return pd.Series(dtype=object)

def make_candlestick_chart(ticker, hist, row, chart_mode="日K", buy_ref=None):
    if hist is None or hist.empty:
        return None

    x = hist.copy()

    if chart_mode == "15m":
        x["EMA9"] = x["Close"].ewm(span=9, adjust=False).mean()
        x["EMA20"] = x["Close"].ewm(span=20, adjust=False).mean()
        typical = (x["High"] + x["Low"] + x["Close"]) / 3
        session = pd.Series(x.index.date, index=x.index)
        x["VWAP"] = (
            (typical * x["Volume"]).groupby(session).cumsum()
            / x["Volume"].groupby(session).cumsum().replace(0, np.nan)
        )
    else:
        x["MA20"] = x["Close"].rolling(20).mean()
        x["MA50"] = x["Close"].rolling(50).mean()

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.76, 0.24]
    )

    fig.add_trace(
        go.Candlestick(
            x=x.index, open=x["Open"], high=x["High"], low=x["Low"], close=x["Close"],
            name=chart_mode,
            increasing_line_color="#0f9d76", decreasing_line_color="#e54b4b",
            increasing_fillcolor="#0f9d76", decreasing_fillcolor="#e54b4b",
        ),
        row=1, col=1
    )

    if chart_mode == "15m":
        for c, name, color in [
            ("EMA9", "EMA9", "#6f42c1"),
            ("EMA20", "EMA20", "#2d7ff9"),
            ("VWAP", "VWAP", "#f28e2b"),
        ]:
            fig.add_trace(
                go.Scatter(x=x.index, y=x[c], mode="lines", name=name,
                           line=dict(width=1.5, color=color)),
                row=1, col=1
            )
    else:
        fig.add_trace(
            go.Scatter(x=x.index, y=x["MA20"], mode="lines", name="MA20",
                       line=dict(width=1.6, color="#2d7ff9")),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(x=x.index, y=x["MA50"], mode="lines", name="MA50",
                       line=dict(width=1.6, color="#f28e2b")),
            row=1, col=1
        )

    vol_colors = np.where(x["Close"] >= x["Open"], "#0f9d76", "#e54b4b")
    fig.add_trace(
        go.Bar(x=x.index, y=x["Volume"], name="成交量",
               marker_color=vol_colors, opacity=0.75),
        row=2, col=1
    )

    last_px = level_value(row, ["最后价格", "价格", "当前价"])
    entry = level_value(row, ["参考入场", "实际买入价"])
    stop = level_value(row, ["参考止损", "持仓止损", "动态保护价"])
    tp1 = level_value(row, ["TP1"])
    tp2 = level_value(row, ["TP2"])

    support_low, support_high = range_bounds(row.get("支撑区", row.get("A5.2R支撑区", "")))
    resist_low, resist_high = range_bounds(row.get("压力区", row.get("A5.2R压力区", "")))

    shapes, annotations = [], []

    def add_hline(y, color, label, dash="dot"):
        if pd.isna(y):
            return
        shapes.append(dict(
            type="line", xref="paper", x0=0, x1=1, yref="y", y0=y, y1=y,
            line=dict(color=color, width=1.3, dash=dash)
        ))
        annotations.append(dict(
            x=1.0, xref="paper", y=y, yref="y", text=label,
            showarrow=False, xanchor="left", font=dict(size=11, color=color)
        ))

    def add_zone(y0, y1, color, label):
        if pd.isna(y0) or pd.isna(y1):
            return
        shapes.append(dict(
            type="rect", xref="paper", x0=0, x1=1, yref="y", y0=y0, y1=y1,
            fillcolor=color, opacity=0.10, line=dict(width=0)
        ))
        annotations.append(dict(
            x=0.01, xref="paper", y=(y0 + y1) / 2, yref="y",
            text=label, showarrow=False, xanchor="left", font=dict(size=10)
        ))

    add_hline(last_px, "#18a36b", f"现价 {last_px:.2f}" if not pd.isna(last_px) else "")
    add_hline(entry, "#6f42c1", f"参考入场 {entry:.2f}" if not pd.isna(entry) else "")
    add_hline(stop, "#d62728", f"Stop {stop:.2f}" if not pd.isna(stop) else "")
    add_hline(tp1, "#2ca02c", f"TP1 {tp1:.2f}" if not pd.isna(tp1) else "")
    add_hline(tp2, "#0b7d4f", f"TP2 {tp2:.2f}" if not pd.isna(tp2) else "")

    add_zone(support_low, support_high, "#2ca02c", "A支撑区")
    add_zone(resist_low, resist_high, "#d62728", "A压力区")

    if buy_ref and buy_ref.get("valid"):
        add_zone(
            buy_ref["pullback_low"], buy_ref["pullback_high"],
            "#8e44ad", "15m回踩关注区"
        )
        add_hline(
            buy_ref["breakout"], "#d35400",
            f"突破触发 {buy_ref['breakout']:.2f}", dash="dash"
        )

    fig.update_layout(
        height=500, margin=dict(l=8, r=72, t=20, b=8),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        shapes=shapes, annotations=annotations,
        plot_bgcolor="#0e355b", paper_bgcolor="#0e355b", font=dict(color="#d5e8fb", size=10),
    )

    for rr in [1, 2]:
        fig.update_xaxes(showgrid=True, gridcolor="rgba(137,173,210,0.10)", row=rr, col=1)
        fig.update_yaxes(showgrid=True, gridcolor="rgba(137,173,210,0.10)", row=rr, col=1)

    return fig



def filter_decision_rows(master, kind):
    if master is None or master.empty:
        return pd.DataFrame()
    c = first_existing(master, ["最后决策", "B决策", "决策"])
    if not c:
        return pd.DataFrame()

    vals = master[c].astype(str)
    k = kind.upper()

    if k == "BUY":
        mask = vals.str.contains("BUY", case=False, na=False) & ~vals.str.contains("EARLY", case=False, na=False)
    elif k == "EARLY":
        mask = vals.str.contains("EARLY", case=False, na=False)
    elif k == "WAIT":
        mask = vals.str.contains("WAIT", case=False, na=False)
    elif k == "AVOID":
        mask = vals.str.contains("AVOID", case=False, na=False)
    else:
        return pd.DataFrame()

    x = master[mask].copy()
    if "Ticker" in x.columns:
        x = x.drop_duplicates(subset=["Ticker"], keep="last")
    return x

def summary_detail_table(df, mode):
    if df is None or df.empty:
        return pd.DataFrame()

    if mode == "A":
        wanted = [
            "Ticker","Company","A5决策","Rank","共振数","空间等级",
            "上方空间","支撑区","压力区","Confidence"
        ]
    elif mode in {"BUY","EARLY","WAIT","AVOID"}:
        wanted = [
            "Ticker","Company","最后决策","最后价格","1H状态",
            "15m RSI","15m量比","参考入场","参考止损","TP1","TP2",
            "空间等级","最后决策依据"
        ]
    elif mode == "HOLD":
        wanted = [
            "Ticker","Company","C阶段","最后价格","实际买入价","最高浮盈%",
            "动态保护价","持仓止损","TP1","TP2","最后决策","最后决策依据"
        ]
    elif mode == "ALERT":
        return latest_alerts(df, 30)
    else:
        wanted = list(df.columns)

    cols = [c for c in wanted if c in df.columns]
    return df[cols].copy()


# ---------- sidebar ----------
with st.sidebar:
    st.markdown("## 📈 CMS")
    st.caption("Unified App V1.9.2 · 一个网址看完整 A + B + C")
    page = st.radio(
        "功能",
        [
            "🏠 首页",
            "🔍 A 选股",
            "⚡ B 买点监控",
            "💼 C 持仓管理",
            "🔔 Alert Center",
            "📊 股票详情",
            "🧾 交易记录 / 收益",
        ],
        label_visibility="collapsed"
    )

    st.divider()
    auto = st.toggle("自动刷新", value=True)
    refresh_seconds = st.selectbox("刷新频率", [60, 120, 300, 900], index=0)

    if st.button("🔄 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption(
        "V1 先做统一界面：A/B/C 核心计算逻辑保持冻结，"
        "继续读取现有 Google Sheet。"
    )

if auto and st_autorefresh is not None:
    st_autorefresh(interval=int(refresh_seconds * 1000), key="cms_unified_refresh")


# ---------- load ----------
try:
    a_df = load_sheet(A_WORKSHEET)
    master_df = load_sheet(B_MASTER_WORKSHEET)
    log_df = load_sheet(B_LOG_WORKSHEET)
except Exception as e:
    st.error(f"读取 Google Sheet 失败：{e}")
    st.stop()

a_buy = latest_a_buys(a_df)
master_latest = latest_master_snapshot(master_df)
master_active = active_master(master_latest)
pos_df = holdings(master_latest)
counts = decision_counts(master_active)
now = market_now()

_sync_col = first_existing(
    master_latest,
    ["最后检查时间", "检查时间", "更新时间", "Timestamp", "时间"]
)
if _sync_col and not master_latest.empty:
    _sync_series = pd.to_datetime(master_latest[_sync_col], errors="coerce")
    latest_bc_sync = _sync_series.max() if _sync_series.notna().any() else pd.NaT
else:
    latest_bc_sync = pd.NaT


# ---------- global header ----------
hl, hr = st.columns([4, 1])
with hl:
    st.markdown('<div class="cms-title">CMS TRADING DESK</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="cms-subtitle">A 选什么 · B 什么时候买 · C 买后怎么管</div>',
        unsafe_allow_html=True
    )
with hr:
    if market_open(now):
        st.success(f"● MARKET OPEN\n\n{now.strftime('%H:%M ET')}")
    else:
        st.info(f"○ MARKET CLOSED\n\n{now.strftime('%H:%M ET')}")

sync_txt = (
    latest_bc_sync.strftime("%Y-%m-%d %H:%M:%S")
    if pd.notna(latest_bc_sync)
    else "暂无"
)
st.caption(
    "Unified App V1.9.2：一个网址统一查看 A、B、C；"
    f"B/C 最新同步：{sync_txt}。"
    "买入区域/突破价仅做参考解释，不改变已经冻结的 B/C 决策逻辑。"
)

# ============================================================
# HOME
# ============================================================
if page == "🏠 首页":
    if "home_summary_view" not in st.session_state:
        st.session_state["home_summary_view"] = None

    m1, m2, m3, m4, m5 = st.columns(5)

    with m1:
        with st.container(key="summary_card_a"):
            if st.button(
                f"🔎 今日 A 正式候选\n{len(a_buy)}\n通过 A 主程序完整筛选，进入 B 监控",
                key="card_a_click",
                use_container_width=True
            ):
                st.session_state["home_summary_view"] = "A"

    with m2:
        with st.container(key="summary_card_buy"):
            if st.button(
                f"📈 B 确认买入（BUY）\n{counts.get('BUY', 0)}\nB 买点监控已确认符合当前买入条件",
                key="card_buy_click",
                use_container_width=True
            ):
                st.session_state["home_summary_view"] = "BUY"

    with m3:
        with st.container(key="summary_card_early"):
            if st.button(
                f"🕒 B 早期机会（EARLY）\n{counts.get('EARLY', 0)}\n接近买入条件，等待突破或回踩确认",
                key="card_early_click",
                use_container_width=True
            ):
                st.session_state["home_summary_view"] = "EARLY"

    with m4:
        with st.container(key="summary_card_hold"):
            if st.button(
                f"💼 当前持仓\n{len(pos_df)}\n已经买入并仍在 C 持仓管理中的股票",
                key="card_hold_click",
                use_container_width=True
            ):
                st.session_state["home_summary_view"] = "HOLD"

    with m5:
        with st.container(key="summary_card_alert"):
            if st.button(
                f"🔔 今日检查 / 提醒\n{alert_today_count(log_df)}\n来自 B_Log 的今日监控、检查与提醒记录",
                key="card_alert_click",
                use_container_width=True
            ):
                st.session_state["home_summary_view"] = "ALERT"

    active_summary = st.session_state.get("home_summary_view")

    if active_summary:
        st.markdown("#### 📌 首页统计明细")

        if active_summary == "A":
            detail_df = summary_detail_table(a_buy, "A")
            title = f"今日 A 正式候选 · {len(a_buy)} 只"
        elif active_summary == "BUY":
            buy_df = filter_decision_rows(master_active, "BUY")
            detail_df = summary_detail_table(buy_df, "BUY")
            title = f"B BUY · {len(buy_df)} 只"
        elif active_summary == "EARLY":
            early_df = filter_decision_rows(master_active, "EARLY")
            detail_df = summary_detail_table(early_df, "EARLY")
            title = f"B EARLY · {len(early_df)} 只"
        elif active_summary == "HOLD":
            detail_df = summary_detail_table(pos_df, "HOLD")
            title = f"真实持仓 · {len(pos_df)} 只"
        else:
            detail_df = summary_detail_table(log_df, "ALERT")
            title = f"最近检查 / 提醒"

        hc1, hc2 = st.columns([6, 1])
        with hc1:
            st.markdown(f"**{title}**")
        with hc2:
            if st.button("关闭明细", key="close_home_summary", use_container_width=True):
                st.session_state["home_summary_view"] = None
                st.rerun()

        if detail_df is None or detail_df.empty:
            st.info("当前没有可显示的记录。")
        else:
            st.dataframe(
                detail_df,
                hide_index=True,
                use_container_width=True,
                height=min(360, 75 + 38 * len(detail_df))
            )

        # Quick drill-down into a selected stock when applicable
        if active_summary in {"A", "BUY", "EARLY", "HOLD"} and detail_df is not None and not detail_df.empty and "Ticker" in detail_df.columns:
            tickers_detail = detail_df["Ticker"].dropna().astype(str).str.upper().drop_duplicates().tolist()
            if tickers_detail:
                selected_from_summary = st.selectbox(
                    "快速查看该组中的股票",
                    tickers_detail,
                    key=f"summary_ticker_{active_summary}"
                )
                if selected_from_summary:
                    row_s = latest_row_for_ticker(selected_from_summary, master_latest, a_df)
                    hs = load_price_history(selected_from_summary, "3mo", "1d")
                    if not hs.empty:
                        fig_s = make_candlestick_chart(selected_from_summary, hs, row_s)
                        if fig_s is not None:
                            st.plotly_chart(
                                fig_s,
                                use_container_width=True,
                                config={"displaylogo": False}
                            )

        st.divider()

    st.divider()
    lcol, rcol = st.columns([0.93, 1.67], gap="medium")

    with lcol:
        st.markdown('<div style="font-size:1.18rem;font-weight:800;color:#eef6ff;margin:0 0 .15rem 0;">🔥 Today\'s Opportunities</div>', unsafe_allow_html=True)
        st.caption("精选机会 · 点击股票查看右侧交易计划、入场条件与图表")
        opp = compact_opportunity_table(master_active)
        if opp.empty:
            st.info("目前没有活跃的 B 候选。")
        else:
            for _, row in opp.head(6).iterrows():
                tk = str(row.get("Ticker", "")).strip().upper()
                company = str(row.get("Company", "")).strip()
                dec = status_badge(row.get("最后决策", ""))
                px = money_text(row.get("最后价格", np.nan))
                room = str(row.get("空间等级", "—"))
                reason = str(row.get("最后决策依据", "")).strip()
                one_h = str(row.get("1H状态", "—"))
                rsi = sfloat(row.get("15m RSI", np.nan))
                vol_ratio = sfloat(row.get("15m量比", np.nan))
                rank = row.get("Rank", "—")

                selected_now = st.session_state.get("home_ticker", "") == tk
                selected_mark = "▶ " if selected_now else ""
                company_txt = ""
                if company and company.lower() not in {"nan", "none"}:
                    company_txt = f"  ·  {company}"

                tech_bits = [f"1H {one_h}"]
                if not pd.isna(rsi): tech_bits.append(f"RSI {rsi:.1f}")
                if not pd.isna(vol_ratio): tech_bits.append(f"量比 {vol_ratio:.2f}")
                if str(rank).strip().lower() not in {"", "nan", "none", "—"}: tech_bits.append(f"Rank {rank}")

                card_text = f"{selected_mark}{dec}   {tk}{company_txt}"
                card_text += f"\n{px}   ·   {room}"
                card_text += "\n" + "   |   ".join(tech_bits)
                if reason:
                    card_text += f"\n{reason[:125]}"

                with st.container(key=f"opportunity_card_{tk}"):
                    if st.button(card_text, key=f"opportunity_click_{tk}", use_container_width=True):
                        st.session_state["home_ticker"] = tk
                        st.session_state["home_selected_from_opportunity"] = tk
                        st.rerun()

        st.markdown('<div style="font-size:1.05rem;font-weight:780;color:#eef6ff;margin:.7rem 0 .25rem 0;">💼 Positions</div>', unsafe_allow_html=True)
        psmall = compact_position_table(pos_df)
        if psmall.empty:
            st.caption("目前没有标记为真实持仓的股票。")
        else:
            showcols = [c for c in ["Ticker","C阶段","最后价格","最高浮盈%","动态保护价"] if c in psmall.columns]
            st.dataframe(psmall[showcols], hide_index=True, use_container_width=True)

    with rcol:
        tickers = union_tickers(master_active, a_buy)
        home_options = tickers if tickers else [""]
        current_home = st.session_state.get("home_ticker")
        if current_home not in home_options:
            st.session_state["home_ticker"] = home_options[0]

        selected_home = st.selectbox("快速切换股票", home_options, key="home_ticker")
        if selected_home:
            row = latest_row_for_ticker(selected_home, master_latest, a_df)
            company = str(row.get("Company", "")).strip()
            decision = status_badge(row.get("最后决策", "—"))
            reason = str(row.get("最后决策依据", "")).strip()
            update_txt = "—"
            for _uc in ["最后检查时间", "检查时间", "更新时间", "Timestamp", "时间"]:
                if _uc in row.index:
                    _dtv = pd.to_datetime(row.get(_uc), errors="coerce")
                    if pd.notna(_dtv):
                        update_txt = _dtv.strftime("%m-%d %H:%M")
                        break
            company_show = "" if company.lower() in {"nan", "none"} else company

            st.markdown(
                f'''<div class="cms-detail-head">
                  <div class="cms-section-label">ACTIVE OPPORTUNITY</div>
                  <div class="cms-detail-ticker">{decision} &nbsp; {selected_home}</div>
                  <div class="cms-detail-company">{company_show} &nbsp;&nbsp; · &nbsp;&nbsp; Last sync {update_txt}</div>
                </div>''',
                unsafe_allow_html=True
            )

            st.markdown('<div style="font-size:1.08rem;font-weight:800;color:#eef6ff;margin:.25rem 0 .35rem 0;">🎯 Trade Plan 交易计划</div>', unsafe_allow_html=True)
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("当前价", money_text(row.get("最后价格", row.get("价格", np.nan))))
            k2.metric("参考入场", money_text(row.get("参考入场", np.nan)))
            k3.metric("Stop", money_text(row.get("参考止损", row.get("持仓止损", np.nan))))
            k4.metric("TP1", money_text(row.get("TP1", np.nan)))
            k5.metric("TP2", money_text(row.get("TP2", np.nan)))

            h15 = load_price_history(selected_home, "10d", "15m")
            buy_ref = calc_buy_reference(h15)

            st.markdown('<div style="font-size:1.08rem;font-weight:800;color:#eef6ff;margin:.65rem 0 .35rem 0;">📊 Entry Setup 入场条件</div>', unsafe_allow_html=True)
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("15m回踩区", buy_reference_text(buy_ref))
            q2.metric("突破触发价", money_text(buy_ref.get("breakout", np.nan)) if buy_ref.get("valid") else "—")
            q3.metric("距回踩区", distance_text(buy_ref.get("dist_pullback_pct", np.nan)))
            q4.metric("当前结构", buy_ref.get("setup_type", "—"))
            st.caption("Entry Setup 只解释 B v1.8 的位置条件；正式入场仍以 B 的 BUY / EARLY / WAIT / AVOID 为准。")

            st.markdown('<div style="font-size:1.08rem;font-weight:800;color:#eef6ff;margin:.65rem 0 .35rem 0;">📊 Decision Context 决策依据</div>', unsafe_allow_html=True)
            z1, z2, z3, z4, z5 = st.columns(5)
            z1.metric("1H", str(row.get("1H状态", "—")))
            rv = sfloat(row.get("15m RSI", np.nan)); vv = sfloat(row.get("15m量比", np.nan))
            z2.metric("15m RSI", f"{rv:.1f}" if not pd.isna(rv) else "—")
            z3.metric("15m量比", f"{vv:.2f}" if not pd.isna(vv) else "—")
            z4.metric("空间", str(row.get("空间等级", "—")))
            z5.metric("共振", str(row.get("共振数", "—")))
            if reason:
                st.markdown(f'<div class="cms-reason"><b>CMS 判断：</b> {reason}</div>', unsafe_allow_html=True)

            chart_mode = st.radio("图表周期", ["15m", "1H", "日K"], horizontal=True, key="home_chart_mode")
            if chart_mode == "15m":
                h = h15; chart_title = f"{selected_home} · 15分钟"
            elif chart_mode == "1H":
                h = load_price_history(selected_home, "3mo", "60m"); chart_title = f"{selected_home} · 1小时"
            else:
                h = load_price_history(selected_home, "3mo", "1d"); chart_title = f"{selected_home} · 3个月日K"

            if not h.empty:
                st.markdown(f"#### {chart_title}")
                fig = make_candlestick_chart(selected_home, h, row, chart_mode=chart_mode, buy_ref=buy_ref)
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
            else:
                st.warning("暂时无法取得该周期行情数据。")

            with st.expander("查看 A / B 完整字段"):
                tmp = pd.DataFrame([row]).T.reset_index()
                tmp.columns = ["字段", "值"]
                st.dataframe(tmp, hide_index=True, use_container_width=True, height=420)


# ============================================================
# A
# ============================================================
elif page == "🔍 A 选股":
    st.subheader("🔍 A · 盘后选股")
    st.caption(
        "这里展示 A FINAL 的结果。V1 不在统一 App 内重新计算 A，"
        "避免动到已经冻结的选股核心。"
    )

    a1, a2, a3 = st.columns(3)
    a1.metric("当前 A 表记录", len(a_df))
    a2.metric("今日正式“买”", len(a_buy))
    if not a_buy.empty and "共振数" in a_buy.columns:
        avg_res = pd.to_numeric(a_buy["共振数"], errors="coerce").mean()
        a3.metric("买入候选平均共振", f"{avg_res:.1f}" if pd.notna(avg_res) else "—")
    else:
        a3.metric("买入候选平均共振", "—")

    st.markdown("#### 今日正式“买”候选")
    if a_buy.empty:
        st.info("今天没有 A FINAL 正式判定为“买”的候选。")
    else:
        wanted = [
            "Ticker","Company","A5决策","Rank","共振数","空间等级","空间优先级",
            "上方空间","支撑区","压力区","Confidence","MACD","KDJ","RSI","RS"
        ]
        cols = [c for c in wanted if c in a_buy.columns]
        st.dataframe(a_buy[cols], hide_index=True, use_container_width=True, height=430)

    with st.expander("查看 A_Candidates 当前完整表"):
        st.dataframe(a_df, hide_index=True, use_container_width=True, height=520)


# ============================================================
# B
# ============================================================
elif page == "⚡ B 买点监控":
    st.subheader("⚡ B · 盘中买点监控")
    st.caption(
        "B 使用已完成的 1H + 15min 逻辑。这里集中展示当前候选、BUY、EARLY、WAIT、AVOID。"
    )

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("BUY", counts.get("BUY", 0))
    b2.metric("EARLY BUY", counts.get("EARLY", 0))
    b3.metric("WAIT", counts.get("WAIT", 0))
    b4.metric("AVOID", counts.get("AVOID", 0))

    opp = compact_opportunity_table(master_active)
    if opp.empty:
        st.info("B_MasterList 当前没有活跃候选。")
    else:
        st.dataframe(opp, hide_index=True, use_container_width=True, height=590)

    st.info(
        "正式 B/C LIVE 程序仍负责实际 15 分钟检查和写入。"
        "Unified App V1 暂时只读取结果。"
    )


# ============================================================
# C
# ============================================================
elif page == "💼 C 持仓管理":
    st.subheader("💼 C · Position Manager")
    st.caption(
        "实际买入后才进入 C。C0 → C1 → C2 → C3 分阶段保护；"
        "初始 Stop 已使用 FINAL v1.8 的 1.50×止损距离。"
    )

    p = compact_position_table(pos_df)
    if p.empty:
        st.info("目前没有标记为真实持仓的股票。")
    else:
        c1, c2 = st.columns([2, 1])
        with c1:
            st.dataframe(p, hide_index=True, use_container_width=True, height=520)
        with c2:
            if "C阶段" in pos_df.columns:
                dist = pos_df["C阶段"].astype(str).value_counts().rename_axis("C阶段").reset_index(name="数量")
                st.markdown("#### C 阶段分布")
                st.bar_chart(dist.set_index("C阶段"))

        for _, row in pos_df.iterrows():
            tk = str(row.get("Ticker",""))
            with st.expander(f"{tk} · 持仓详情"):
                p1,p2,p3,p4 = st.columns(4)
                p1.metric("实际买入价", money_text(row.get("实际买入价", np.nan)))
                p2.metric("最后价格", money_text(row.get("最后价格", np.nan)))
                p3.metric("最高浮盈%", pct_text(row.get("最高浮盈%", np.nan)))
                p4.metric("动态保护价", money_text(row.get("动态保护价", np.nan)))
                st.write("C阶段：", row.get("C阶段","—"))
                st.write("最后决策：", row.get("最后决策","—"))
                reason = str(row.get("最后决策依据","")).strip()
                if reason:
                    st.caption(reason)

    st.info(
        "V1 里持仓的“标记 / 修改实际买入价 / 手动更新”仍在 B/C FINAL v1.8 LIVE App 完成。"
        "下一阶段可把这些操作搬进这里。"
    )


# ============================================================
# ALERT
# ============================================================
elif page == "🔔 Alert Center":
    st.subheader("🔔 Alert Center")
    st.caption("集中查看 B_Log 最近的检查与提醒记录。")

    alerts = latest_alerts(log_df, 100)
    if alerts.empty:
        st.info("B_Log 暂无记录。")
    else:
        st.dataframe(alerts, hide_index=True, use_container_width=True, height=650)

    st.warning(
        "当前仍依赖 Streamlit App 运行。真正的后台 15 分钟监控和手机/邮件推送，"
        "是下一阶段产品化的重点。"
    )


# ============================================================
# DETAIL
# ============================================================
elif page == "📊 股票详情":
    st.subheader("📊 Stock Detail")

    tickers = union_tickers(master_latest, a_df)
    if not tickers:
        st.info("目前没有股票可查看。")
    else:
        d1, d2 = st.columns([1, 3])
        with d1:
            tk = st.selectbox("股票", tickers, key="detail_ticker")
            period = st.selectbox("图表区间", ["1mo","3mo","6mo","1y"], index=1, format_func=lambda x: {"1mo":"1个月","3mo":"3个月","6mo":"6个月","1y":"1年"}[x])
        with d2:
            row = latest_row_for_ticker(tk, master_latest, a_df)
            title_company = str(row.get("Company", ""))
            st.markdown(f"### {tk} {title_company}")

        h15 = load_price_history(tk, "10d", "15m")
        buy_ref = calc_buy_reference(h15)

        st.markdown("#### 🎯 买点参考")
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("15m回踩关注区", buy_reference_text(buy_ref))
        b2.metric(
            "突破触发价",
            money_text(buy_ref.get("breakout", np.nan)) if buy_ref.get("valid") else "—"
        )
        b3.metric("距回踩区", distance_text(buy_ref.get("dist_pullback_pct", np.nan)))
        b4.metric("买点类型", buy_ref.get("setup_type", "—"))

        detail_mode = st.radio(
            "图表周期",
            ["15m", "1H", "日K"],
            horizontal=True,
            key="detail_chart_mode"
        )

        if detail_mode == "15m":
            hist = h15
        elif detail_mode == "1H":
            hist = load_price_history(tk, "3mo", "60m")
        else:
            hist = load_price_history(tk, period, "1d")

        if not hist.empty:
            fig = make_candlestick_chart(
                tk, hist, row,
                chart_mode=detail_mode,
                buy_ref=buy_ref
            )
            if fig is not None:
                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    config={"displaylogo": False}
                )
        else:
            st.warning("该周期行情暂时不可用。")

        st.caption(
            "买点参考只解释 B 的位置条件；真正入场仍由 B v1.8 的实时 BUY 触发决定。"
        )

        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("最后价格", money_text(row.get("最后价格", row.get("价格", np.nan))))
        r2.metric("参考入场", money_text(row.get("参考入场", np.nan)))
        r3.metric("参考止损", money_text(row.get("参考止损", row.get("持仓止损", np.nan))))
        r4.metric("TP1", money_text(row.get("TP1", np.nan)))
        r5.metric("TP2", money_text(row.get("TP2", np.nan)))

        st.markdown("#### CMS 状态")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("A", str(row.get("A5决策", "—")))
        c2.metric("B", status_badge(row.get("最后决策", "—")))
        c3.metric("C阶段", str(row.get("C阶段", "—")))
        c4.metric("1H", str(row.get("1H状态", "—")))
        c5.metric("空间", str(row.get("空间等级", "—")))
        c6.metric("共振数", str(row.get("共振数", "—")))

        reason = str(row.get("最后决策依据", "")).strip()
        if reason:
            st.markdown("#### 决策依据")
            st.info(reason)

        with st.expander("查看该股票完整记录"):
            tmp = pd.DataFrame([row]).T.reset_index()
            tmp.columns = ["字段", "值"]
            st.dataframe(tmp, hide_index=True, use_container_width=True)


# ============================================================
# TRADE / PERFORMANCE PLACEHOLDER
# ============================================================
elif page == "🧾 交易记录 / 收益":
    st.subheader("🧾 交易记录 / 收益")
    st.caption("这是 Unified App V1 预留的产品页面。")

    st.info(
        "目前 B_MasterList / B_Log 还不是完整的真实交易账本，"
        "所以 V1 不会编造收益数据。"
    )

    st.markdown(
        """
        下一版这里可以正式加入：

        - 每笔真实买入 / 卖出记录
        - 已实现收益与未实现收益
        - 胜率、平均盈利、平均亏损
        - 最大单笔回撤
        - A → B → C 每一阶段的贡献
        - 月度收益曲线
        - 哪类 BUY（突破 / 回踩）表现最好
        """
    )

    st.markdown("#### 当前可用的 B_Log")
    recent = latest_alerts(log_df, 40)
    if recent.empty:
        st.caption("暂无记录。")
    else:
        st.dataframe(recent, hide_index=True, use_container_width=True, height=450)


st.divider()
st.caption(
    "CMS Unified App V1.9.2 · 首页机会卡片可点击 + B/C最新状态同步 + 15m回踩关注区 + 突破触发位 + 15m/1H/日K切换。"
    "策略核心保持冻结。后续再把“运行 A、真实 B 后台监控、持仓操作、收益统计”逐步搬进同一个 App。"
)
