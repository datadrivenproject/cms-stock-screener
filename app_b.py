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

st.set_page_config(page_title="CMS B/C FINAL v1.8 LIVE — 最终实盘版", page_icon="🎯", layout="wide")
st.title("🎯 CMS Stock Screener B/C FINAL v1.8 LIVE — 最终实盘版")
st.caption("B只负责A正式“买”候选的盘中择时；C负责真实持仓后的止损/止盈/HOLD。A负责选什么，B/C负责什么时候买、买后什么时候处理。")

A_WORKSHEET = "A_Candidates"
A_HISTORY_WORKSHEET = "A_AllScannedHistory"
B_LOG_WORKSHEET = "B_Log"
B_MASTER_WORKSHEET = "B_MasterList"

SHEET_CN_MAP = {'Scan Date': '扫描日期', 'Scan Time': '扫描时间', 'Ticker': '股票代码', 'Company': '公司', 'Sector': '板块', 'Market Cap': '市值', 'Price': '价格', 'ATR14': 'ATR14', 'RVOL': 'RVOL', 'Dollar Volume': '成交额', '5D Return': '5日涨跌幅', '20D Return': '20日涨跌幅', 'Rank': '排名', 'Early V2 Score': 'Early V2总分', 'Confidence': '信心等级', 'Fundamental Confirmation': '基本面确认', 'Fundamental Reason': '基本面依据', 'Quality Fundamental': '质量', 'FCF Fundamental': '现金流', 'Debt Fundamental': '负债', 'Valuation Fundamental': '估值', 'Growth Fundamental': '增长', 'ROE': 'ROE', 'Operating Margin': '营业利润率', 'Free Cash Flow': '自由现金流', 'Operating Cash Flow': '经营现金流', 'Debt to Equity': 'Debt/Equity', 'Forward PE': 'Forward P/E', 'PEG': 'PEG', 'EV/EBITDA': 'EV/EBITDA', 'Revenue Growth': '营收增长', 'Earnings Growth': '盈利增长', 'Structure Score': '市场结构分', 'Trend & Momentum Score': '趋势动量分', 'Accumulation Score': '资金积累分', 'Leadership Score': '相对强势分', 'Catalyst Score': '催化剂分', 'Major Resistance Zone': '主要压力区', 'Resistance Touches': '压力测试次数', 'Resistance Strength': '压力强度', 'Major Support Zone': '主要支撑区', 'Support Touches': '支撑测试次数', 'Short-term Breakout': '短期突破位', 'Distance to Major Resistance': '距主要压力', 'Distance to Short Breakout': '距短期突破', 'Compression Ratio': '压缩比', 'R→S Flip': 'R→S转换', 'R→S Flip Zone': 'R→S回踩区', 'R→S Flip Touches': 'R→S历史测试次数', 'MA20': 'MA20', 'MA50': 'MA50', 'MA200': 'MA200', 'MA20 Slope 5D': 'MA20 5日斜率', 'MACD': 'MACD', 'MACD Signal': 'MACD信号', 'MACD Histogram': 'MACD柱', 'MACD Phase': 'MACD阶段', 'RSI14': 'RSI14', 'Volume Build Ratio': '量能增强比', 'Up/Down Volume Ratio': '涨跌量比', 'OBV Trend': 'OBV趋势', 'OBV Positive Divergence': 'OBV正背离', 'Stock vs SPY 20D': '个股 vs SPY 20日', 'Sector vs SPY 20D': '板块 vs SPY 20日', 'Stock vs Sector 20D': '个股 vs 板块 20日', 'Stock vs SPY 5D': '个股 vs SPY 5日', 'RS Acceleration': 'RS加速度', 'Sector ETF': '板块ETF', 'Catalyst Label': '催化剂状态', 'Positive Catalyst': '正面催化剂', 'Negative Catalyst': '负面催化剂', 'Headlines': '相关新闻', 'Hard Filter': '硬筛选', 'Hard Filter Reason': '硬筛选原因', 'CMS Context': 'CMS参考'}

SHEET_CN_MAP.update({
    "A5决策": "结果",
    "共振数": "共振数",
    "空间等级": "空间等级",
    "空间优先级": "空间优先级",
    "位置判断": "位置判断",
    "A5.2R支撑区": "支撑区",
    "A5.2R压力区": "压力区",
    "上方空间": "上方空间",
})

SHEET_INTERNAL_MAP = {v:k for k,v in SHEET_CN_MAP.items()}
B_DISPLAY_CN_MAP = {**SHEET_CN_MAP, "Ticker":"股票代码", "Company":"公司", "Rank":"排名", "Confidence":"信心等级", "Fundamental Confirmation":"基本面确认", "Early V2 Score":"Early V2总分"}
B_MASTER_PRIMARY = ["Ticker","Company","池状态","是否持仓","A5决策","空间等级","空间优先级","上方空间","最后决策","最后价格","实际买入价","持仓止损","TP1","TP2","C阶段","持仓最高价","最高浮盈%","动态保护价","利润回吐%","最近入选日期","跟踪天数","观察剩余天数","最后检查时间","最后决策依据","Rank","共振数","Early V2 Score","Confidence","Fundamental Confirmation","首次进入B","最近同步A","实际买入日期","退出日期","退出价","退出原因"]

def normalize_sheet_columns(df):
    if df is None or df.empty: return df
    return df.rename(columns={c:SHEET_INTERNAL_MAP.get(c,c) for c in df.columns})

def chinese_sheet_columns(df):
    if df is None: return df
    return df.rename(columns=B_DISPLAY_CN_MAP)

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

def safe_percent_value(x, default=np.nan):
    """Accept numeric fractions or sheet strings such as '+3.4%', 'None', ''."""
    try:
        if x is None or pd.isna(x):
            return default
    except Exception:
        pass
    s = str(x).strip()
    if s == "" or s.lower() in {"none", "nan", "n/a", "na", "未识别"}:
        return default
    try:
        if s.endswith("%"):
            return float(s[:-1].replace(",", "").replace("+", "")) / 100.0
        return float(s.replace(",", "").replace("+", ""))
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


@st.cache_data(ttl=900)
def get_replay_intraday(ticker, interval, start_date, end_date):
    """历史回放专用：一次下载日期区间数据，避免逐根K线反复请求。"""
    try:
        start_ts = pd.to_datetime(start_date) - pd.Timedelta(days=14)
        end_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        df = yf.download(
            ticker,
            interval=interval,
            start=start_ts.strftime("%Y-%m-%d"),
            end=end_ts.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            threads=False,
            prepost=False
        )
        x = flatten_yf(df)
        if x is None or x.empty:
            return None
        # 统一成纽约时间，便于15m与60m按时间切片比较。
        if getattr(x.index, "tz", None) is None:
            x.index = x.index.tz_localize(MARKET_TZ)
        else:
            x.index = x.index.tz_convert(MARKET_TZ)
        return x.sort_index()
    except Exception:
        return None


def replay_one_ticker(row, start_date, end_date):
    """
    用过去真实K线逐个15分钟时点重放B的同一套decision逻辑。
    只记录状态变化，避免输出几百行重复WAIT。
    """
    ticker = str(row["Ticker"]).strip().upper()
    m15_all = get_replay_intraday(ticker, "15m", start_date, end_date)
    h1_all = get_replay_intraday(ticker, "60m", start_date, end_date)

    if m15_all is None or m15_all.empty:
        return pd.DataFrame(), f"{ticker}: 15m历史数据不足"
    if h1_all is None or h1_all.empty:
        return pd.DataFrame(), f"{ticker}: 60m历史数据不足"

    start_ts = pd.Timestamp(start_date).tz_localize(MARKET_TZ)
    end_ts = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize(MARKET_TZ)

    # 仅回放常规美股交易时段内的15分钟K。
    bars = m15_all[
        (m15_all.index >= start_ts) &
        (m15_all.index < end_ts)
    ].copy()

    if bars.empty:
        return pd.DataFrame(), f"{ticker}: 所选日期没有15m交易数据"

    rows = []
    prev_status = None

    for ts in bars.index:
        # 必须只使用“当时已经发生”的数据，避免未来函数。
        m15_slice = m15_all[m15_all.index <= ts]
        h1_slice = h1_all[h1_all.index <= ts]

        h1 = evaluate_1h(h1_slice)
        m15 = evaluate_15m(m15_slice)
        d, reason, entry, stop = decision(row, h1, m15)

        # 只保留状态变化；首次也保留。
        if d != prev_status:
            rows.append({
                "时间": ts.strftime("%Y-%m-%d %H:%M"),
                "股票代码": ticker,
                "状态": d,
                "当前价格": m15.get("price", np.nan),
                "1H状态": h1.get("status", "DATA"),
                "15m RSI": m15.get("rsi", np.nan),
                "15m量比": m15.get("volratio", np.nan),
                "突破幅度%": (safe_float(m15.get("breakout_extension", np.nan))*100 if not pd.isna(safe_float(m15.get("breakout_extension", np.nan))) else np.nan),
                "VWAP上方": "是" if m15.get("above_vwap") else "否",
                "15m突破": "是" if m15.get("breakout") else "否",
                "15m回踩": "是" if m15.get("pullback") else "否",
                "参考入场": entry,
                "参考止损": stop,
                "决策依据": reason
            })
            prev_status = d

    return pd.DataFrame(rows), None

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



def get_a_history_sheet():
    """A完整历史扫描池；只读，不创建、不修改。"""
    if gspread is None or Credentials is None:
        raise RuntimeError("requirements.txt需要gspread和google-auth。")
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
    return book.worksheet(A_HISTORY_WORKSHEET)


@st.cache_data(ttl=900, show_spinner=False)
def load_a_history_pool_cached():
    """
    Read A_AllScannedHistory and return a normalized DataFrame.
    Cache 15 minutes so repeated Streamlit reruns do not keep hitting Google Sheets.
    """
    ws = get_a_history_sheet()
    rec = ws.get_all_records()
    if not rec:
        return pd.DataFrame()
    df = normalize_sheet_columns(pd.DataFrame(rec))
    if "Ticker" in df.columns:
        df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    return df


def build_a_history_ticker_pool(start_date=None, end_date=None):
    """
    Expand the research ticker pool from A_AllScannedHistory.
    If a scan-date column exists, limit pool to tickers that appeared during
    the requested historical window. This function only chooses which tickers
    to test; LIVE B/C is untouched.
    """
    try:
        hist = load_a_history_pool_cached().copy()
    except Exception as e:
        return pd.DataFrame(), f"读取 {A_HISTORY_WORKSHEET} 失败：{e}"

    if hist.empty or "Ticker" not in hist.columns:
        return pd.DataFrame(), f"{A_HISTORY_WORKSHEET} 为空或缺少股票代码列"

    # Find scan date after normalization. Older history versions may use different names.
    date_col = next(
        (c for c in ["Scan Date","Date","扫描日期","日期"] if c in hist.columns),
        None
    )

    if date_col is not None and start_date is not None and end_date is not None:
        d = pd.to_datetime(hist[date_col], errors="coerce").dt.date
        mask = d.notna() & (d >= start_date) & (d <= end_date)
        scoped = hist[mask].copy()
        # If the selected window predates the accumulated sheet, fall back to all
        # available A-history tickers rather than returning zero names.
        if not scoped.empty:
            hist = scoped

    tickers = (
        hist["Ticker"]
        .astype(str)
        .str.strip()
        .str.upper()
    )
    tickers = tickers[
        tickers.ne("") &
        tickers.ne("NAN") &
        tickers.ne("NONE")
    ]

    pool = pd.DataFrame({"Ticker": sorted(tickers.drop_duplicates().tolist())})
    return pool, None


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
        df = normalize_sheet_columns(pd.DataFrame(rec))
        if "Ticker" in df.columns:
            df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
        return df
    except Exception:
        return pd.DataFrame()

def save_b_master(df):
    ws = get_or_create_b_master_sheet()
    if ws is None:
        return False
    try:
        x = df.copy() if df is not None else pd.DataFrame()
        x = x.replace([np.inf,-np.inf],np.nan).fillna("")
        first = [c for c in B_MASTER_PRIMARY if c in x.columns]
        rest = [c for c in x.columns if c not in first]
        x = chinese_sheet_columns(x[first+rest].copy())
        ws.clear()
        if not x.empty:
            ws.update([list(x.columns)] + x.astype(str).values.tolist(), "A1")
        return True
    except Exception:
        return False


def business_day_age(last_date, current_date):
    """
    计算从最近一次A入选日至当前A扫描日的工作日天数（含首尾）。
    例如：同一天=1；下一个工作日=2。
    注：这里按周一至周五计算，不额外识别美股节假日。
    """
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
    """
    V1.6核心：
    - A_Candidates每天可以被覆盖，只需要保留“今天”的A结果。
    - B_MasterList负责真正累计历史候选，每只Ticker只保留一行。
    - 今天再次被A选中：更新最近入选日期，并把5日观察期重新从1开始。
    - 今天未被A选中：Master仍保留；按最近入选日期继续计算5个交易日。
    - 超过5个交易日且未持仓：EXPIRED。
    - 已持仓：HOLDING，不受5日限制。
    """
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

    # 每只Ticker只保留Master中最后一行，避免历史误重复。
    if not m.empty:
        m = m.drop_duplicates("Ticker", keep="last").copy()

    required_defaults = {
        "是否持仓": "否",
        "池状态": "TRACKING",
        "首次进入B": "",
        "最近入选日期": "",
        "跟踪天数": "",
        "观察剩余天数": "",
        "最近同步A": ""
    }
    for c, default in required_defaults.items():
        if c not in m.columns:
            m[c] = default

    # 先按Master已有记录重新计算状态，不因为今天A覆盖就删除旧候选。
    for idx, row in m.iterrows():
        is_holding = str(row.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]
        if is_holding:
            m.at[idx, "池状态"] = "HOLDING"
            m.at[idx, "观察剩余天数"] = "持仓不受限"
            continue

        last_pick = row.get("最近入选日期","")
        age = business_day_age(last_pick, current_day)
        if pd.isna(age):
            # 旧Master缺最近入选日期时，不直接删除，先保留TRACKING等待下一次A同步修复。
            m.at[idx, "池状态"] = "TRACKING"
            continue

        age = int(age)
        m.at[idx, "跟踪天数"] = age
        m.at[idx, "观察剩余天数"] = max(0, 6 - age)
        m.at[idx, "池状态"] = "TRACKING" if age <= 5 else "EXPIRED"

    # 处理今天A的候选：追加新Ticker；重复Ticker只更新最新A字段并重置5日计时。
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

        # 当天再次入选 = 重新开始5交易日观察窗口。
        new["最近入选日期"] = current_day_str
        new["跟踪天数"] = 1
        new["观察剩余天数"] = 5
        new["最近同步A"] = now

        is_holding = str(old.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]
        new["是否持仓"] = "是" if is_holding else "否"
        new["池状态"] = "HOLDING" if is_holding else "TRACKING"

        # 如果以前已经CLOSED，但今天重新被A选中，则允许重新进入观察池。
        if str(old.get("池状态","")).upper() == "CLOSED" and not is_holding:
            new["退出日期"] = old.get("退出日期","")
            new["退出价"] = old.get("退出价","")
            new["退出原因"] = old.get("退出原因","")

        rows[t] = new

    out = pd.DataFrame(list(rows.values())) if rows else pd.DataFrame(columns=["Ticker"])
    if not out.empty:
        out["Ticker"] = out["Ticker"].astype(str).str.upper()
        state_order = {"HOLDING":0, "TRACKING":1, "EXPIRED":2, "CLOSED":3}
        out["_state_order"] = out.get("池状态","").map(state_order).fillna(9)
        out = out.sort_values(["_state_order","Ticker"], kind="stable").drop(columns="_state_order").reset_index(drop=True)
    return out

def active_master_pool(master, max_candidates=20):
    """所有真实持仓都监控；非持仓候选最多取max_candidates只。"""
    if master is None or master.empty:
        return pd.DataFrame()
    x = master.copy()
    hold = x[x.get("池状态","").astype(str).eq("HOLDING")].copy() if "池状态" in x.columns else pd.DataFrame()
    watch = x[x.get("池状态","").astype(str).eq("TRACKING")].copy() if "池状态" in x.columns else pd.DataFrame()
    if not watch.empty and "A5决策" in watch.columns:
        watch = watch[watch["A5决策"].astype(str).str.strip().eq("买")].copy()

    if not watch.empty:
        watch["_room_priority"] = pd.to_numeric(watch.get("空间优先级", 0), errors="coerce").fillna(0)
        watch["_rank"] = pd.to_numeric(watch.get("Rank", np.nan), errors="coerce")
        watch = watch.sort_values(
            ["最近入选日期","_room_priority","_rank"],
            ascending=[False,False,True],
            na_position="last"
        ).drop(columns=["_room_priority","_rank"])
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
    x.loc[mask,"C阶段"] = "C0 初始保护"
    x.loc[mask,"持仓最高价"] = float(entry) if entry else ""
    x.loc[mask,"最高浮盈%"] = 0.0
    x.loc[mask,"动态保护价"] = float(stop) if stop else ""
    x.loc[mask,"利润回吐%"] = 0.0
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
        df = normalize_sheet_columns(pd.DataFrame(rec))
        if "Ticker" not in df.columns or "盘中决策" not in df.columns:
            return {}
        if "检查时间" in df.columns:
            df["_dt"] = pd.to_datetime(df["检查时间"], errors="coerce")
            df = df.sort_values("_dt")
        latest = df.drop_duplicates("Ticker", keep="last")
        return dict(zip(latest["Ticker"].astype(str).str.upper(), latest["盘中决策"].astype(str)))
    except Exception:
        return {}

def append_b_log(out, run_time):
    try:
        ws = get_or_create_b_log_sheet()
        if ws is None or out is None or out.empty:
            return False
        log = out.copy()
        log.insert(0,"检查时间",run_time.strftime("%Y-%m-%d %H:%M:%S"))
        log.insert(1,"检查日期",run_time.strftime("%Y-%m-%d"))
        log = chinese_sheet_columns(log.replace([np.inf,-np.inf],np.nan).fillna(""))
        existing = ws.get_all_values()
        headers = list(log.columns)
        if not existing or existing[0] != headers:
            ws.clear(); ws.update([headers] + log.astype(str).values.tolist(), "A1")
        else:
            ws.append_rows(log.astype(str).values.tolist(), value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


@st.cache_data(ttl=300)
def load_latest_a_candidates():
    """
    A_Candidates允许每天覆盖。
    B这里只读取A表“最新扫描日”的当日候选，不再假设A表保存最近5天。
    历史5日累计完全由B_MasterList负责。
    """
    ws = get_a_sheet()
    rec = ws.get_all_records()
    if not rec:
        return pd.DataFrame(), None

    df = normalize_sheet_columns(pd.DataFrame(rec))
    if "Ticker" not in df.columns:
        raise RuntimeError("A_Candidates 缺少‘股票代码’列。")

    date_col = next((c for c in ["Scan Date","Date","日期","扫描日期"] if c in df.columns), None)
    if date_col is None:
        raise RuntimeError("A_Candidates 缺少‘扫描日期’列。")

    df["_scan_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df[df["_scan_date"].notna()].copy()
    if df.empty:
        return pd.DataFrame(), None

    latest_day = df["_scan_date"].max()
    today = df[df["_scan_date"].eq(latest_day)].copy()
    today["Ticker"] = today["Ticker"].astype(str).str.strip().str.upper()
    today = today.drop_duplicates("Ticker", keep="last")

    # B/C FINAL only accepts A5.2R FINAL rows whose formal A decision is “买”.
    if "A5决策" not in today.columns:
        raise RuntimeError("A_Candidates 缺少‘结果’列。请先用 A5.2R FINAL v1 保存当天候选。")
    today = today[today["A5决策"].astype(str).str.strip().eq("买")].copy()
    if today.empty:
        return pd.DataFrame(), latest_day.strftime("%Y-%m-%d")

    if "Rank" in today.columns:
        today["Rank"] = pd.to_numeric(today["Rank"], errors="coerce")
        today = today.sort_values("Rank", ascending=True, na_position="last")

    today["最近入选日期"] = latest_day.strftime("%Y-%m-%d")
    today["跟踪天数"] = 1
    today["观察剩余天数"] = 5
    today["池状态"] = "TRACKING"

    return today.reset_index(drop=True), latest_day.strftime("%Y-%m-%d")


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
    breakout_extension = ((price-ph)/ph) if (breakout and not pd.isna(ph) and ph>0) else np.nan
    macd_positive = (hist > 0) if not pd.isna(hist) else False
    return {
        "valid":True,"price":price,"vwap":vwap,"ema9":e9,"ema20":e20,"rsi":rsi,"atr":atr,
        "volratio":volratio,"breakout":breakout,"near":near,"above_vwap":above_vwap,
        "ema_structure":ema_structure,"macd_improving":macd_improving,"macd_positive":macd_positive,
        "breakout_extension":breakout_extension,"pullback":pullback,
        "overextended":overextended
    }


def _high_since_entry(df15, entry_dt, fallback_price=np.nan):
    """Use observed 15m highs since the real buy timestamp; fallback to current price."""
    if df15 is None or df15.empty:
        return fallback_price
    try:
        x = df15.copy()
        if "High" not in x.columns:
            return fallback_price
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
                mask = x.index >= entry_dt
                hi = hi.loc[mask]
            except Exception:
                pass
        v = safe_float(hi.max(), np.nan)
        if pd.isna(v):
            return fallback_price
        return max(v, fallback_price) if not pd.isna(fallback_price) else v
    except Exception:
        return fallback_price


def calc_c_stage(entry, original_stop, peak_price):
    """
    Conservative staged protection.
    Important: C does NOT tighten at +1%/+2%. This avoids the old over-selling problem.

    C0: peak < +4%      -> keep original stop.
    C1: +4% to <+6%    -> protect around breakeven (-0.25% buffer).
    C2: +6% to <+10%   -> keep at least +2% OR 40% of peak profit.
    C3: peak >= +10%    -> keep at least +4% OR 60% of peak profit.
    """
    if pd.isna(entry) or entry <= 0 or pd.isna(peak_price):
        return "C0 初始保护", original_stop, np.nan

    peak_ret = (peak_price / entry - 1.0)
    stop0 = original_stop if (not pd.isna(original_stop) and original_stop > 0) else np.nan

    if peak_ret < 0.04:
        stage = "C0 初始保护"
        dyn = stop0
    elif peak_ret < 0.06:
        stage = "C1 保本区"
        breakeven_buffer = entry * 0.9975
        dyn = max([v for v in [stop0, breakeven_buffer] if not pd.isna(v)])
    elif peak_ret < 0.10:
        stage = "C2 利润保护"
        protect_ret = max(0.02, peak_ret * 0.40)
        profit_stop = entry * (1.0 + protect_ret)
        dyn = max([v for v in [stop0, profit_stop] if not pd.isna(v)])
    else:
        stage = "C3 强趋势保护"
        protect_ret = max(0.04, peak_ret * 0.60)
        profit_stop = entry * (1.0 + protect_ret)
        dyn = max([v for v in [stop0, profit_stop] if not pd.isna(v)])

    return stage, dyn, peak_ret * 100.0


def c_trend_warning(h1, m15):
    """Trend deterioration is a warning, not an automatic sell by itself."""
    if not h1.get("valid") or not m15.get("valid"):
        return False
    price = safe_float(m15.get("price", np.nan))
    vwap = safe_float(m15.get("vwap", np.nan))
    e20 = safe_float(m15.get("ema20", np.nan))
    below_intraday = (
        not pd.isna(price) and
        ((not pd.isna(vwap) and price < vwap) or (not pd.isna(e20) and price < e20))
    )
    return h1.get("status") == "弱" and below_intraday


def analyze_holding(row):
    """
    C FINAL staged exit logic.
    Real holdings are NOT subject to the 5-day candidate expiry.
    Priority: hard/original stop -> dynamic profit protection -> TP2 -> TP1 -> trend warning -> HOLD.
    """
    ticker = str(row["Ticker"]).strip().upper()

    h1_df = get_intraday(ticker, "60m", "3mo")
    m15_df = get_intraday(ticker, "15m", "10d")
    h1 = evaluate_1h(h1_df)
    m15 = evaluate_15m(m15_df)

    price = safe_float(m15.get("price", np.nan))
    entry = safe_float(row.get("实际买入价", np.nan))
    original_stop = safe_float(row.get("持仓止损", np.nan))
    tp1 = safe_float(row.get("TP1", np.nan))
    tp2 = safe_float(row.get("TP2", np.nan))

    entry_dt = pd.to_datetime(row.get("实际买入日期", ""), errors="coerce")
    peak_price = _high_since_entry(m15_df, entry_dt, fallback_price=price)
    stage, dynamic_stop, peak_ret_pct = calc_c_stage(entry, original_stop, peak_price)

    pnl = ((price-entry)/entry*100) if (not pd.isna(price) and not pd.isna(entry) and entry>0) else np.nan
    giveback = peak_ret_pct - pnl if (not pd.isna(peak_ret_pct) and not pd.isna(pnl)) else np.nan
    trend_warn = c_trend_warning(h1, m15)

    # C exit priority.
    if pd.isna(price):
        d = "⚪ DATA"
        reason = "持仓行情数据不足"
    elif not pd.isna(original_stop) and original_stop > 0 and price <= original_stop:
        d = "🛑 STOP LOSS"
        reason = f"现价{price:.2f}已触及原始止损{original_stop:.2f}"
    elif (
        stage in ["C1 保本区", "C2 利润保护", "C3 强趋势保护"]
        and not pd.isna(dynamic_stop) and dynamic_stop > 0
        and price <= dynamic_stop
    ):
        d = "🔻 PROFIT PROTECT"
        reason = (
            f"{stage}触发动态保护：现价{price:.2f} ≤ 保护价{dynamic_stop:.2f}；"
            f"最高浮盈{peak_ret_pct:.1f}% / 当前{pnl:.1f}%"
        )
    elif not pd.isna(tp2) and tp2 > 0 and price >= tp2:
        d = "🟣 TAKE PROFIT TP2"
        reason = f"现价{price:.2f}已达到TP2 {tp2:.2f}"
    elif not pd.isna(tp1) and tp1 > 0 and price >= tp1:
        d = "🟠 TAKE PROFIT TP1"
        reason = f"现价{price:.2f}已达到TP1 {tp1:.2f}；可考虑分批止盈，不强制全部退出"
    elif trend_warn and not pd.isna(pnl) and pnl > 0:
        d = "🟡 HOLD / 趋势转弱"
        reason = "1H转弱且15m跌回VWAP/EMA20下方；先警戒，不因单次转弱自动卖出"
    else:
        d = "🟢 HOLD"
        if stage == "C0 初始保护":
            reason = "尚未达到+4%峰值，继续使用原始止损，避免1–2%小波动过早退出"
        else:
            reason = f"{stage}；动态保护价{dynamic_stop:.2f}" if not pd.isna(dynamic_stop) else stage

    return {
        "Ticker":ticker,
        "最近入选日期":row.get("最近入选日期",""),
        "跟踪天数":row.get("跟踪天数",""),
        "观察剩余天数":"持仓不受限",
        "池状态":"HOLDING",
        "A结果":row.get("A5决策",""),
        "A空间等级":row.get("空间等级",""),
        "A空间优先级":row.get("空间优先级",""),
        "A上方空间":row.get("上方空间",np.nan),
        "A排名":row.get("Rank",""),
        "A共振数":row.get("共振数",""),
        "A Early V2":row.get("Early V2 Score",""),
        "A信心":row.get("Confidence",row.get("信心等级","")),
        "A基本面":row.get("Fundamental Confirmation",row.get("基本面确认","")),

        "当前价格":price,
        "盘中决策":d,
        "决策依据":reason,
        "持仓成本":entry,
        "持仓盈亏%":pnl,

        "C阶段":stage,
        "持仓最高价":peak_price,
        "最高浮盈%":peak_ret_pct,
        "动态保护价":dynamic_stop,
        "利润回吐%":giveback,
        "趋势转弱警报":"是" if trend_warn else "否",

        "1H状态":h1.get("status","DATA"),
        "1H RSI":h1.get("rsi",np.nan),
        "15m VWAP":m15.get("vwap",np.nan),
        "15m EMA9":m15.get("ema9",np.nan),
        "15m EMA20":m15.get("ema20",np.nan),
        "15m RSI":m15.get("rsi",np.nan),
        "15m量比":m15.get("volratio",np.nan),
        "15m突破":"是" if m15.get("breakout") else "否",
        "15m回踩":"是" if m15.get("pullback") else "否",
        "VWAP上方":"是" if m15.get("above_vwap") else "否",
        "避免追高":"是" if m15.get("overextended") else "否",

        "参考入场":entry,
        "参考止损":original_stop,
        "TP1":tp1,
        "TP2":tp2
    }


def weak_fundamental(row):
    f=str(row.get("Fundamental Confirmation",row.get("基本面确认",""))).lower()
    c=str(row.get("Confidence",row.get("信心等级",""))).lower()
    return ("weak" in f) or ("弱" in f) or c in ["low","低"]


LIVE_INITIAL_STOP_MULTIPLIER = 1.50

def apply_live_initial_stop(entry_px, base_stop):
    """
    V1.8 LIVE final rule:
    keep the original B stop *structure*, but widen the distance from entry by 1.50x.

    Example:
      entry=100, old/base stop=99  -> base distance=1
      V1.8 LIVE stop = 100 - 1.50*1 = 98.50

    This does not change BUY timing. It only changes the initial protective stop
    that is handed from B to C after a real purchase.
    """
    entry_px = safe_float(entry_px, np.nan)
    base_stop = safe_float(base_stop, np.nan)

    if pd.isna(entry_px) or entry_px <= 0:
        return np.nan
    if pd.isna(base_stop) or base_stop <= 0 or base_stop >= entry_px:
        return base_stop

    base_dist = entry_px - base_stop
    return max(0.01, entry_px - LIVE_INITIAL_STOP_MULTIPLIER * base_dist)


def decision(row,h1,m15):
    if not h1.get("valid"): return "⚪ DATA",h1.get("reason","1H数据不足"),np.nan,np.nan
    if not m15.get("valid"): return "⚪ DATA",m15.get("reason","15min数据不足"),np.nan,np.nan
    if h1["status"]=="弱": return "🔴 AVOID","1H趋势/动量未确认",np.nan,np.nan
    if m15["overextended"]: return "🟡 WAIT","偏离VWAP/EMA20过大或RSI过热，避免追高",np.nan,np.nan
    if not m15["above_vwap"]: return "🟡 WAIT","价格仍在VWAP下方",np.nan,np.nan

    # V2.1：只收紧“突破BUY”，回踩BUY保持V2.0完全不变。
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

    pullback_buy = h1["status"] in ["强","中等"] and m15["pullback"] and m15["macd_improving"] and (pd.isna(m15["volratio"]) or m15["volratio"]>=0.80)

    if breakout_buy:
        stop=min(m15["vwap"],m15["ema20"])-0.35*m15["atr"]
        return "🟢 BUY","V2.1突破确认：1H强 + 15min真实突破 + MACD为正 + RSI 50–70 + 量比≥1.50 + 突破不追高",m15["price"],stop
    if pullback_buy:
        stop=min(m15["vwap"],m15["ema20"])-0.35*m15["atr"]
        return "🟢 BUY","1H趋势保持 + 15min健康回踩 + 动量改善",m15["price"],stop
    if m15["near"] and m15["macd_improving"] and m15["above_vwap"]:
        return "🟠 EARLY BUY","接近15min突破位，动量改善且位于VWAP上方；等待正式突破/回踩确认",np.nan,np.nan
    return "🟡 WAIT","结构尚可，但15min触发条件未齐",np.nan,np.nan


def buy_gate_diagnosis(h1, m15):
    """Explain which BUY gates pass/fail without changing live decision logic."""
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
        "VWAP上方": bool(m15.get("above_vwap")),
        "不过热": not bool(m15.get("overextended")),
    }
    pb = {
        "1H≥中等": h1.get("status") in ["强","中等"],
        "回踩": bool(m15.get("pullback")),
        "MACD改善": bool(m15.get("macd_improving")),
        "量比≥0.80": (pd.isna(safe_float(m15.get("volratio", np.nan))) or safe_float(m15.get("volratio", np.nan)) >= 0.80),
        "VWAP上方": bool(m15.get("above_vwap")),
        "不过热": not bool(m15.get("overextended")),
    }

    br_fail = [k for k,v in br.items() if not v]
    pb_fail = [k for k,v in pb.items() if not v]

    if not br_fail:
        return "突破BUY全部通过"
    if not pb_fail:
        return "回踩BUY全部通过"

    br_txt = "、".join(br_fail[:4]) if br_fail else "无"
    pb_txt = "、".join(pb_fail[:4]) if pb_fail else "无"
    return f"突破缺：{br_txt}；回踩缺：{pb_txt}"

def analyze_one(row):
    if str(row.get("池状态","")).upper() == "HOLDING" or str(row.get("是否持仓","否")).upper() in ["是","Y","YES","TRUE","1"]:
        return analyze_holding(row)
    ticker=str(row["Ticker"]).strip().upper()
    h1=evaluate_1h(get_intraday(ticker,"60m","3mo"))
    m15=evaluate_15m(get_intraday(ticker,"15m","10d"))
    d,reason,entry,base_stop=decision(row,h1,m15)
    stop = apply_live_initial_stop(entry, base_stop)
    if d == "🟢 BUY" and not pd.isna(safe_float(stop, np.nan)):
        reason = reason + f"；V1.8初始Stop采用原止损距离×{LIVE_INITIAL_STOP_MULTIPLIER:.2f}"
    gate_diag = buy_gate_diagnosis(h1,m15)
    return {
        "Ticker":ticker,"最近入选日期":row.get("最近入选日期",""),"跟踪天数":row.get("跟踪天数",""),"观察剩余天数":row.get("观察剩余天数",""),"池状态":row.get("池状态","TRACKING"),
        "A结果":row.get("A5决策",""),"A空间等级":row.get("空间等级",""),"A空间优先级":row.get("空间优先级",""),"A上方空间":row.get("上方空间",np.nan),
        "A排名":row.get("Rank",""),"A共振数":row.get("共振数",""),"A Early V2":row.get("Early V2 Score",""),
        "A信心":row.get("Confidence",row.get("信心等级","")),
        "A基本面":row.get("Fundamental Confirmation",row.get("基本面确认","")),
        "当前价格":m15.get("price",np.nan),"盘中决策":d,"决策依据":reason,"BUY门槛诊断":gate_diag,
        "1H状态":h1.get("status","DATA"),"1H RSI":h1.get("rsi",np.nan),
        "15m VWAP":m15.get("vwap",np.nan),"15m EMA9":m15.get("ema9",np.nan),
        "15m EMA20":m15.get("ema20",np.nan),"15m RSI":m15.get("rsi",np.nan),
        "15m量比":m15.get("volratio",np.nan),"15m突破":"是" if m15.get("breakout") else "否",
        "15m回踩":"是" if m15.get("pullback") else "否","VWAP上方":"是" if m15.get("above_vwap") else "否",
        "避免追高":"是" if m15.get("overextended") else "否",
        "1H强":"是" if h1.get("status")=="强" else "否",
        "1H至少中等":"是" if h1.get("status") in ["强","中等"] else "否",
        "15m EMA结构":"是" if m15.get("ema_structure") else "否",
        "15m MACD正":"是" if m15.get("macd_positive") else "否",
        "15m MACD改善":"是" if m15.get("macd_improving") else "否",
        "突破RSI合格":"是" if (not pd.isna(safe_float(m15.get("rsi",np.nan))) and 50 <= safe_float(m15.get("rsi",np.nan)) <= 70) else "否",
        "突破量比≥1.50":"是" if (not pd.isna(safe_float(m15.get("volratio",np.nan))) and safe_float(m15.get("volratio",np.nan)) >= 1.50) else "否",
        "回踩量比≥0.80":"是" if (pd.isna(safe_float(m15.get("volratio",np.nan))) or safe_float(m15.get("volratio",np.nan)) >= 0.80) else "否",
        "突破不追高":"是" if (pd.isna(safe_float(m15.get("breakout_extension",np.nan))) or safe_float(m15.get("breakout_extension",np.nan)) <= 0.008) else "否",
        "接近突破位":"是" if m15.get("near") else "否",
        "参考入场":entry,"基础止损":base_stop,"参考止损":stop
    }


# =========================================================
# C HISTORICAL BACKTEST — RESEARCH ONLY
# =========================================================
def _trading_day_horizon_bars(m15_all, entry_ts, trading_days=3):
    if m15_all is None or m15_all.empty:
        return pd.DataFrame()
    x = m15_all[m15_all.index > entry_ts].copy()
    if x.empty:
        return x
    try:
        mins = x.index.hour * 60 + x.index.minute
        x = x[(mins >= 9*60+30) & (mins <= 16*60)]
    except Exception:
        pass
    if x.empty:
        return x
    dates = pd.Series(x.index.date).drop_duplicates().tolist()
    allowed = set(dates[:max(1, int(trading_days))])
    return x[[d in allowed for d in x.index.date]].copy()


def _future_max_return_after_exit(path, exit_ts, entry_px):
    if path is None or path.empty or pd.isna(exit_ts) or pd.isna(entry_px) or entry_px <= 0:
        return np.nan
    future = path[path.index > exit_ts]
    if future.empty:
        return np.nan
    h = pd.to_numeric(future["High"], errors="coerce").max()
    return ((h / entry_px) - 1.0) * 100.0 if not pd.isna(h) else np.nan


def _path_peak_return(path, entry_px):
    if path is None or path.empty or pd.isna(entry_px) or entry_px <= 0:
        return np.nan
    h = pd.to_numeric(path["High"], errors="coerce").max()
    return ((h / entry_px) - 1.0) * 100.0 if not pd.isna(h) else np.nan


def _exit_at_horizon(path, entry_px, label):
    if path is None or path.empty:
        return None
    px = safe_float(path["Close"].iloc[-1])
    ts = path.index[-1]
    ret = ((px / entry_px) - 1.0) * 100.0 if entry_px > 0 else np.nan
    peak = _path_peak_return(path, entry_px)
    giveback = peak - ret if not pd.isna(peak) and not pd.isna(ret) else np.nan
    capture = (ret / peak * 100.0) if (not pd.isna(peak) and peak > 0 and not pd.isna(ret)) else np.nan
    return {
        "策略": label, "退出时间": ts, "退出价": px, "退出原因": f"{label}到期",
        "最终收益%": ret, "路径最高浮盈%": peak, "利润回吐%": giveback,
        "峰值保留率%": capture, "过早退出机会成本%": 0.0
    }


def _simulate_hard_stop(path, entry_px, initial_stop):
    if path is None or path.empty:
        return None
    stop = safe_float(initial_stop, np.nan)
    for ts, bar in path.iterrows():
        low = safe_float(bar.get("Low", np.nan))
        if not pd.isna(stop) and stop > 0 and not pd.isna(low) and low <= stop:
            px = stop
            ret = (px / entry_px - 1.0) * 100.0
            used = path[path.index <= ts]
            peak = _path_peak_return(used, entry_px)
            giveback = peak - ret if not pd.isna(peak) else np.nan
            capture = (ret / peak * 100.0) if (not pd.isna(peak) and peak > 0) else np.nan
            opp = _future_max_return_after_exit(path, ts, entry_px)
            return {
                "策略":"原始Stop only","退出时间":ts,"退出价":px,"退出原因":"原始STOP",
                "最终收益%":ret,"路径最高浮盈%":peak,"利润回吐%":giveback,
                "峰值保留率%":capture,
                "过早退出机会成本%":max(0.0, opp-ret) if not pd.isna(opp) else np.nan
            }
    return _exit_at_horizon(path, entry_px, "原始Stop only")


def _simulate_fixed_tp5(path, entry_px, initial_stop):
    if path is None or path.empty:
        return None
    stop = safe_float(initial_stop, np.nan)
    tp = entry_px * 1.05
    for ts, bar in path.iterrows():
        low = safe_float(bar.get("Low", np.nan))
        high = safe_float(bar.get("High", np.nan))
        if not pd.isna(stop) and stop > 0 and not pd.isna(low) and low <= stop:
            px, reason = stop, "原始STOP"
        elif not pd.isna(high) and high >= tp:
            px, reason = tp, "固定TP +5%"
        else:
            continue
        ret = (px / entry_px - 1.0) * 100.0
        used = path[path.index <= ts]
        peak = _path_peak_return(used, entry_px)
        giveback = peak - ret if not pd.isna(peak) else np.nan
        capture = (ret / peak * 100.0) if (not pd.isna(peak) and peak > 0) else np.nan
        opp = _future_max_return_after_exit(path, ts, entry_px)
        return {
            "策略":"固定TP5% + Stop","退出时间":ts,"退出价":px,"退出原因":reason,
            "最终收益%":ret,"路径最高浮盈%":peak,"利润回吐%":giveback,
            "峰值保留率%":capture,
            "过早退出机会成本%":max(0.0, opp-ret) if not pd.isna(opp) else np.nan
        }
    return _exit_at_horizon(path, entry_px, "固定TP5% + Stop")


def _simulate_c_v13(path, entry_px, initial_stop):
    if path is None or path.empty:
        return None
    peak_price = entry_px
    current_stage, current_dyn, _ = calc_c_stage(entry_px, initial_stop, peak_price)

    for ts, bar in path.iterrows():
        low = safe_float(bar.get("Low", np.nan))
        high = safe_float(bar.get("High", np.nan))

        if not pd.isna(initial_stop) and initial_stop > 0 and not pd.isna(low) and low <= initial_stop:
            px, reason, exit_stage = initial_stop, "原始STOP", current_stage
        elif (current_stage in ["C1 保本区","C2 利润保护","C3 强趋势保护"]
              and not pd.isna(current_dyn) and current_dyn > 0
              and not pd.isna(low) and low <= current_dyn):
            px, reason, exit_stage = current_dyn, "C分阶段PROFIT PROTECT", current_stage
        else:
            if not pd.isna(high):
                peak_price = max(peak_price, high)
            current_stage, current_dyn, _ = calc_c_stage(entry_px, initial_stop, peak_price)
            continue

        ret = (px / entry_px - 1.0) * 100.0
        used = path[path.index <= ts]
        peak = _path_peak_return(used, entry_px)
        giveback = peak - ret if not pd.isna(peak) else np.nan
        capture = (ret / peak * 100.0) if (not pd.isna(peak) and peak > 0) else np.nan
        opp = _future_max_return_after_exit(path, ts, entry_px)
        return {
            "策略":"C 分阶段","退出时间":ts,"退出价":px,"退出原因":reason,
            "C退出阶段":exit_stage,"最终收益%":ret,"路径最高浮盈%":peak,
            "利润回吐%":giveback,"峰值保留率%":capture,
            "过早退出机会成本%":max(0.0, opp-ret) if not pd.isna(opp) else np.nan
        }

    out = _exit_at_horizon(path, entry_px, "C 分阶段")
    if out is not None:
        out["C退出阶段"] = current_stage
    return out


def historical_buy_entries(row, start_date, end_date):
    ticker = str(row["Ticker"]).strip().upper()
    m15_all = get_replay_intraday(ticker, "15m", start_date, end_date)
    h1_all = get_replay_intraday(ticker, "60m", start_date, end_date)
    if m15_all is None or m15_all.empty or h1_all is None or h1_all.empty:
        return [], m15_all, f"{ticker}: 15m/60m历史数据不足"

    start_ts = pd.Timestamp(start_date).tz_localize(MARKET_TZ)
    end_ts = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize(MARKET_TZ)
    bars = m15_all[(m15_all.index >= start_ts) & (m15_all.index < end_ts)].copy()
    if bars.empty:
        return [], m15_all, f"{ticker}: 所选日期无15m数据"

    entries, prev_status, lock_until_date = [], None, None

    for ts in bars.index:
        if lock_until_date is not None and ts.date() <= lock_until_date:
            continue
        m15_slice = m15_all[m15_all.index <= ts]
        h1_slice = h1_all[h1_all.index <= ts]
        h1 = evaluate_1h(h1_slice)
        m15 = evaluate_15m(m15_slice)
        d, reason, entry_px, stop = decision(row, h1, m15)

        if d == "🟢 BUY" and prev_status != "🟢 BUY" and not pd.isna(entry_px):
            future = _trading_day_horizon_bars(m15_all, ts, 3)
            if not future.empty:
                entries.append({
                    "Ticker":ticker,"BUY时间":ts,"BUY价格":entry_px,"初始止损":stop,
                    "BUY类型":"回踩BUY" if "回踩" in reason else "突破BUY","BUY依据":reason
                })
                future_dates = pd.Series(future.index.date).drop_duplicates().tolist()
                if future_dates:
                    lock_until_date = future_dates[-1]
        prev_status = d

    return entries, m15_all, None


def run_c_historical_backtest(master_rows, start_date, end_date, horizon_days=3):
    all_cases, errors = [], []
    if master_rows is None or master_rows.empty:
        return pd.DataFrame(), pd.DataFrame(), ["没有可回测股票"]

    for _, row in master_rows.iterrows():
        entries, m15_all, err = historical_buy_entries(row, start_date, end_date)
        if err:
            errors.append(err)
            continue
        for e in entries:
            path = _trading_day_horizon_bars(m15_all, e["BUY时间"], horizon_days)
            if path is None or path.empty:
                continue
            strategies = [
                _exit_at_horizon(path, e["BUY价格"], f"Hold {horizon_days}D"),
                _simulate_hard_stop(path, e["BUY价格"], e["初始止损"]),
                _simulate_fixed_tp5(path, e["BUY价格"], e["初始止损"]),
                _simulate_c_v13(path, e["BUY价格"], e["初始止损"]),
            ]
            for s in strategies:
                if s is not None:
                    rec = dict(e); rec.update(s); rec["持有交易日"] = horizon_days
                    all_cases.append(rec)

    detail = pd.DataFrame(all_cases)
    if detail.empty:
        return detail, pd.DataFrame(), errors

    rows = []
    for strategy, g in detail.groupby("策略", sort=False):
        r = pd.to_numeric(g["最终收益%"], errors="coerce")
        peak = pd.to_numeric(g["路径最高浮盈%"], errors="coerce")
        gb = pd.to_numeric(g["利润回吐%"], errors="coerce")
        cap = pd.to_numeric(g["峰值保留率%"], errors="coerce")
        opp = pd.to_numeric(g["过早退出机会成本%"], errors="coerce")
        rows.append({
            "策略":strategy,"样本":len(g),"平均最终收益%":r.mean(),"中位最终收益%":r.median(),
            "胜率>0":(r>0).mean(),"≥3%":(r>=3).mean(),"≥5%":(r>=5).mean(),
            "平均路径最高浮盈%":peak.mean(),"平均利润回吐%":gb.mean(),
            "平均峰值保留率%":cap[cap.notna()].mean(),
            "平均过早退出机会成本%":opp.mean(),
            "STOP/保护退出率":g["退出原因"].astype(str).str.contains("STOP|PROFIT", regex=True).mean(),
            "TP退出率":g["退出原因"].astype(str).str.contains("TP", regex=True).mean(),
        })
    return detail, pd.DataFrame(rows), errors



def _entry_atr15(m15_all, entry_ts):
    """ATR14 from 15m data known at entry time only."""
    if m15_all is None or m15_all.empty:
        return np.nan
    x = m15_all[m15_all.index <= entry_ts].copy()
    if x.empty or len(x) < 20:
        return np.nan
    try:
        a = add_indicators(x)
        return safe_float(a["ATR14"].iloc[-1], np.nan)
    except Exception:
        return np.nan


def _adjust_stop(entry_px, original_stop, mode, atr15=np.nan):
    """
    Widen only. Never tighten the original stop.
    mode:
      当前Stop
      1.25x止损距离
      1.50x止损距离
      2.00x止损距离
      ATR1.5
      ATR2.0
    """
    entry_px = safe_float(entry_px, np.nan)
    original_stop = safe_float(original_stop, np.nan)
    atr15 = safe_float(atr15, np.nan)

    if pd.isna(entry_px) or entry_px <= 0:
        return np.nan

    # fallback distance if original stop is missing/bad
    if pd.isna(original_stop) or original_stop <= 0 or original_stop >= entry_px:
        base_dist = entry_px * 0.02
        original_stop = entry_px - base_dist
    else:
        base_dist = entry_px - original_stop

    if mode == "当前Stop":
        return original_stop
    if mode == "1.25x止损距离":
        return max(0.01, entry_px - 1.25 * base_dist)
    if mode == "1.50x止损距离":
        return max(0.01, entry_px - 1.50 * base_dist)
    if mode == "2.00x止损距离":
        return max(0.01, entry_px - 2.00 * base_dist)

    if mode == "ATR1.5":
        if pd.isna(atr15) or atr15 <= 0:
            return max(0.01, entry_px - 1.50 * base_dist)
        atr_stop = entry_px - 1.50 * atr15
        return min(original_stop, atr_stop)

    if mode == "ATR2.0":
        if pd.isna(atr15) or atr15 <= 0:
            return max(0.01, entry_px - 2.00 * base_dist)
        atr_stop = entry_px - 2.00 * atr15
        return min(original_stop, atr_stop)

    return original_stop


def _max_adverse_excursion(path, entry_px):
    if path is None or path.empty or pd.isna(entry_px) or entry_px <= 0:
        return np.nan
    lo = pd.to_numeric(path["Low"], errors="coerce").min()
    return ((lo / entry_px) - 1.0) * 100.0 if not pd.isna(lo) else np.nan


def run_stop_sensitivity_backtest(master_rows, start_date, end_date, horizon_days=5):
    """
    Same historical B BUY entries; only change initial stop.
    Every stop variant is then fed into the exact same staged C v1.3 logic.
    """
    modes = [
        "当前Stop",
        "1.25x止损距离",
        "1.50x止损距离",
        "2.00x止损距离",
        "ATR1.5",
        "ATR2.0",
    ]

    all_cases = []
    errors = []

    if master_rows is None or master_rows.empty:
        return pd.DataFrame(), pd.DataFrame(), ["没有可回测股票"]

    for _, row in master_rows.iterrows():
        entries, m15_all, err = historical_buy_entries(row, start_date, end_date)
        if err:
            errors.append(err)
            continue

        for e in entries:
            path = _trading_day_horizon_bars(m15_all, e["BUY时间"], horizon_days)
            if path is None or path.empty:
                continue

            atr15 = _entry_atr15(m15_all, e["BUY时间"])
            mae = _max_adverse_excursion(path, e["BUY价格"])

            for mode in modes:
                test_stop = _adjust_stop(
                    e["BUY价格"],
                    e["初始止损"],
                    mode,
                    atr15=atr15
                )
                s = _simulate_c_v13(path, e["BUY价格"], test_stop)
                if s is None:
                    continue

                rec = dict(e)
                rec.update(s)
                rec["Stop方案"] = mode
                rec["测试止损"] = test_stop
                rec["止损距离%"] = ((e["BUY价格"] - test_stop) / e["BUY价格"] * 100.0) if e["BUY价格"] > 0 else np.nan
                rec["入场15m ATR"] = atr15
                rec["路径MAE%"] = mae
                rec["持有交易日"] = horizon_days
                all_cases.append(rec)

    detail = pd.DataFrame(all_cases)
    if detail.empty:
        return detail, pd.DataFrame(), errors

    rows = []
    for mode, g in detail.groupby("Stop方案", sort=False):
        r = pd.to_numeric(g["最终收益%"], errors="coerce")
        peak = pd.to_numeric(g["路径最高浮盈%"], errors="coerce")
        gb = pd.to_numeric(g["利润回吐%"], errors="coerce")
        cap = pd.to_numeric(g["峰值保留率%"], errors="coerce")
        opp = pd.to_numeric(g["过早退出机会成本%"], errors="coerce")
        mae = pd.to_numeric(g["路径MAE%"], errors="coerce")
        stopdist = pd.to_numeric(g["止损距离%"], errors="coerce")

        rows.append({
            "Stop方案": mode,
            "样本": len(g),
            "平均止损距离%": stopdist.mean(),
            "平均最终收益%": r.mean(),
            "中位最终收益%": r.median(),
            "胜率>0": (r > 0).mean(),
            "≥3%": (r >= 3).mean(),
            "≥5%": (r >= 5).mean(),
            "平均路径最高浮盈%": peak.mean(),
            "平均路径MAE%": mae.mean(),
            "平均利润回吐%": gb.mean(),
            "平均峰值保留率%": cap[cap.notna()].mean(),
            "平均过早退出机会成本%": opp.mean(),
            "原始STOP退出率": g["退出原因"].astype(str).eq("原始STOP").mean(),
            "C保护退出率": g["退出原因"].astype(str).str.contains("C分阶段PROFIT PROTECT", regex=False).mean(),
        })

    summary = pd.DataFrame(rows)
    return detail, summary, errors



def _summarize_stop_slice(detail_slice):
    """Same metrics as the main Stop sensitivity table, for one time slice."""
    if detail_slice is None or detail_slice.empty:
        return pd.DataFrame()

    rows = []
    for mode, g in detail_slice.groupby("Stop方案", sort=False):
        r = pd.to_numeric(g["最终收益%"], errors="coerce")
        peak = pd.to_numeric(g["路径最高浮盈%"], errors="coerce")
        gb = pd.to_numeric(g["利润回吐%"], errors="coerce")
        cap = pd.to_numeric(g["峰值保留率%"], errors="coerce")
        opp = pd.to_numeric(g["过早退出机会成本%"], errors="coerce")
        mae = pd.to_numeric(g["路径MAE%"], errors="coerce")
        stopdist = pd.to_numeric(g["止损距离%"], errors="coerce")

        rows.append({
            "Stop方案":mode,
            "样本":len(g),
            "平均止损距离%":stopdist.mean(),
            "平均最终收益%":r.mean(),
            "中位最终收益%":r.median(),
            "胜率>0":(r>0).mean(),
            "≥3%":(r>=3).mean(),
            "≥5%":(r>=5).mean(),
            "平均路径最高浮盈%":peak.mean(),
            "平均路径MAE%":mae.mean(),
            "平均利润回吐%":gb.mean(),
            "平均峰值保留率%":cap[cap.notna()].mean(),
            "平均过早退出机会成本%":opp.mean(),
            "原始STOP退出率":g["退出原因"].astype(str).eq("原始STOP").mean(),
            "C保护退出率":g["退出原因"].astype(str).str.contains("C分阶段PROFIT PROTECT", regex=False).mean(),
        })
    return pd.DataFrame(rows)


def run_stop_stability_validation(master_rows, start_date, end_date, horizon_days=5):
    """
    Final stability validation:
    1) run the same stop sensitivity test on the full window;
    2) split BUY entries chronologically into earlier/later halves;
    3) summarize each half separately;
    4) compare 1.50x vs current Stop and ATR2.0 without changing LIVE.
    """
    detail, summary, errors = run_stop_sensitivity_backtest(
        master_rows, start_date, end_date, horizon_days=horizon_days
    )
    if detail is None or detail.empty:
        return detail, summary, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), errors

    # Unique BUY events, chronologically split by BUY timestamp.
    events = (
        detail[["Ticker","BUY时间"]]
        .drop_duplicates()
        .sort_values("BUY时间")
        .reset_index(drop=True)
    )

    if len(events) < 2:
        return detail, summary, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), errors

    mid = len(events) // 2
    early_events = set(zip(events.iloc[:mid]["Ticker"], events.iloc[:mid]["BUY时间"]))
    late_events = set(zip(events.iloc[mid:]["Ticker"], events.iloc[mid:]["BUY时间"]))

    early_mask = detail.apply(lambda r: (r["Ticker"], r["BUY时间"]) in early_events, axis=1)
    late_mask = detail.apply(lambda r: (r["Ticker"], r["BUY时间"]) in late_events, axis=1)

    early_summary = _summarize_stop_slice(detail[early_mask].copy())
    late_summary = _summarize_stop_slice(detail[late_mask].copy())

    # Direct decision table for the three most relevant contenders.
    contenders = ["当前Stop", "1.50x止损距离", "ATR2.0"]
    checks = []

    def _row(df, mode):
        if df is None or df.empty:
            return None
        x = df[df["Stop方案"].eq(mode)]
        return None if x.empty else x.iloc[0]

    for mode in contenders:
        full = _row(summary, mode)
        early = _row(early_summary, mode)
        late = _row(late_summary, mode)
        if full is None:
            continue
        checks.append({
            "Stop方案":mode,
            "全样本数":int(full["样本"]),
            "全窗平均收益%":full["平均最终收益%"],
            "前半平均收益%":early["平均最终收益%"] if early is not None else np.nan,
            "后半平均收益%":late["平均最终收益%"] if late is not None else np.nan,
            "全窗胜率":full["胜率>0"],
            "前半胜率":early["胜率>0"] if early is not None else np.nan,
            "后半胜率":late["胜率>0"] if late is not None else np.nan,
            "全窗≥5%":full["≥5%"],
            "前半≥5%":early["≥5%"] if early is not None else np.nan,
            "后半≥5%":late["≥5%"] if late is not None else np.nan,
            "全窗过早退出成本%":full["平均过早退出机会成本%"],
            "前半过早退出成本%":early["平均过早退出机会成本%"] if early is not None else np.nan,
            "后半过早退出成本%":late["平均过早退出机会成本%"] if late is not None else np.nan,
            "全窗MAE%":full["平均路径MAE%"],
            "前半MAE%":early["平均路径MAE%"] if early is not None else np.nan,
            "后半MAE%":late["平均路径MAE%"] if late is not None else np.nan,
        })

    compare = pd.DataFrame(checks)
    return detail, summary, early_summary, late_summary, compare, errors


def render_stop_stability(detail, summary, early_summary, late_summary, compare):
    st.subheader("🧪 Stop稳定性最终验证")

    if summary is None or summary.empty:
        st.info("没有足够样本生成稳定性验证。")
        return

    total_buy_events = 0
    if detail is not None and not detail.empty:
        total_buy_events = len(detail[["Ticker","BUY时间"]].drop_duplicates())

    c1,c2,c3 = st.columns(3)
    c1.metric("历史BUY事件", total_buy_events)
    c2.metric("目标样本", "≥100")
    c3.metric("当前状态", "可判断" if total_buy_events >= 100 else "样本仍偏少")

    st.markdown("#### ① 全窗口 Stop 对比")
    st.dataframe(
        summary.style.format({
            "平均止损距离%":"{:.2f}",
            "平均最终收益%":"{:+.2f}",
            "中位最终收益%":"{:+.2f}",
            "胜率>0":"{:.1%}",
            "≥3%":"{:.1%}",
            "≥5%":"{:.1%}",
            "平均路径最高浮盈%":"{:+.2f}",
            "平均路径MAE%":"{:+.2f}",
            "平均利润回吐%":"{:.2f}",
            "平均峰值保留率%":"{:.1f}",
            "平均过早退出机会成本%":"{:.2f}",
            "原始STOP退出率":"{:.1%}",
            "C保护退出率":"{:.1%}",
        }, na_rep=""),
        hide_index=True,
        use_container_width=True
    )

    st.markdown("#### ② 前半段 vs 后半段")
    left, right = st.columns(2)
    with left:
        st.caption("前半段 BUY")
        if early_summary is not None and not early_summary.empty:
            st.dataframe(
                early_summary.style.format({
                    "平均最终收益%":"{:+.2f}",
                    "胜率>0":"{:.1%}",
                    "≥5%":"{:.1%}",
                    "平均过早退出机会成本%":"{:.2f}",
                    "平均路径MAE%":"{:+.2f}",
                    "原始STOP退出率":"{:.1%}",
                }, na_rep=""),
                hide_index=True,
                use_container_width=True
            )
    with right:
        st.caption("后半段 BUY")
        if late_summary is not None and not late_summary.empty:
            st.dataframe(
                late_summary.style.format({
                    "平均最终收益%":"{:+.2f}",
                    "胜率>0":"{:.1%}",
                    "≥5%":"{:.1%}",
                    "平均过早退出机会成本%":"{:.2f}",
                    "平均路径MAE%":"{:+.2f}",
                    "原始STOP退出率":"{:.1%}",
                }, na_rep=""),
                hide_index=True,
                use_container_width=True
            )

    st.markdown("#### ③ 三个最终候选：当前Stop vs 1.50× vs ATR2.0")
    if compare is not None and not compare.empty:
        st.dataframe(
            compare.style.format({
                "全窗平均收益%":"{:+.2f}",
                "前半平均收益%":"{:+.2f}",
                "后半平均收益%":"{:+.2f}",
                "全窗胜率":"{:.1%}",
                "前半胜率":"{:.1%}",
                "后半胜率":"{:.1%}",
                "全窗≥5%":"{:.1%}",
                "前半≥5%":"{:.1%}",
                "后半≥5%":"{:.1%}",
                "全窗过早退出成本%":"{:.2f}",
                "前半过早退出成本%":"{:.2f}",
                "后半过早退出成本%":"{:.2f}",
                "全窗MAE%":"{:+.2f}",
                "前半MAE%":"{:+.2f}",
                "后半MAE%":"{:+.2f}",
            }, na_rep=""),
            hide_index=True,
            use_container_width=True
        )

        current = compare[compare["Stop方案"].eq("当前Stop")]
        x15 = compare[compare["Stop方案"].eq("1.50x止损距离")]
        atr2 = compare[compare["Stop方案"].eq("ATR2.0")]

        if not current.empty and not x15.empty:
            a = current.iloc[0]
            b = x15.iloc[0]

            conds = {
                "全窗收益更高": b["全窗平均收益%"] > a["全窗平均收益%"],
                "前半收益不差": b["前半平均收益%"] >= a["前半平均收益%"],
                "后半收益不差": b["后半平均收益%"] >= a["后半平均收益%"],
                "全窗胜率更高": b["全窗胜率"] > a["全窗胜率"],
                "全窗≥5%更高": b["全窗≥5%"] > a["全窗≥5%"],
                "过早退出成本更低": b["全窗过早退出成本%"] < a["全窗过早退出成本%"],
                "MAE未恶化": b["全窗MAE%"] >= a["全窗MAE%"] - 0.25,
            }
            passed = sum(bool(v) for v in conds.values())
            st.markdown("#### ④ 预先固定的 GO / NO-GO")
            check_df = pd.DataFrame({
                "判定条件": list(conds.keys()),
                "是否通过": ["✅" if v else "❌" for v in conds.values()]
            })
            st.dataframe(check_df, hide_index=True, use_container_width=True)

            if total_buy_events >= 100 and passed >= 6:
                st.success(
                    f"GO：1.50×通过 {passed}/7 项，而且样本≥100。"
                    "可以进入正式LIVE候选。"
                )
            elif total_buy_events >= 100:
                st.warning(
                    f"NO-GO：样本够，但1.50×只通过 {passed}/7 项。"
                    "不建议正式替换当前Stop。"
                )
            else:
                st.info(
                    f"当前1.50×通过 {passed}/7 项，但历史BUY只有 {total_buy_events} 个，"
                    "先把时间窗扩大，尽量做到≥100个BUY事件再定版。"
                )

    csv = detail.to_csv(index=False).encode("utf-8-sig") if detail is not None else b""
    st.download_button(
        "💾 下载稳定性验证逐笔明细",
        csv,
        file_name=f"Stop_Stability_{datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )

def render_stop_sensitivity(detail, summary):
    st.subheader("🧭 初始Stop敏感性 × C联合回测")

    if summary is None or summary.empty:
        st.info("当前范围没有可比较的历史BUY样本。")
        return

    st.dataframe(
        summary.style.format({
            "平均止损距离%":"{:.2f}",
            "平均最终收益%":"{:+.2f}",
            "中位最终收益%":"{:+.2f}",
            "胜率>0":"{:.1%}",
            "≥3%":"{:.1%}",
            "≥5%":"{:.1%}",
            "平均路径最高浮盈%":"{:+.2f}",
            "平均路径MAE%":"{:+.2f}",
            "平均利润回吐%":"{:.2f}",
            "平均峰值保留率%":"{:.1f}",
            "平均过早退出机会成本%":"{:.2f}",
            "原始STOP退出率":"{:.1%}",
            "C保护退出率":"{:.1%}",
        }, na_rep=""),
        hide_index=True,
        use_container_width=True
    )

    st.caption(
        "判断重点：不是止损越宽越好。理想方案应同时做到："
        "平均最终收益/胜率提高、过早退出机会成本下降、STOP退出率下降，"
        "但平均MAE不能明显恶化。"
    )

    # Simple ranked view: emphasize balance, not one metric.
    score = summary.copy()
    for c in ["平均最终收益%","胜率>0","≥5%","平均过早退出机会成本%","平均路径MAE%","原始STOP退出率"]:
        score[c] = pd.to_numeric(score[c], errors="coerce")

    if len(score) >= 2:
        score["综合观察"] = (
            score["平均最终收益%"].rank(pct=True) +
            score["胜率>0"].rank(pct=True) +
            score["≥5%"].rank(pct=True) +
            (-score["平均过早退出机会成本%"]).rank(pct=True) +
            (-score["原始STOP退出率"]).rank(pct=True) +
            score["平均路径MAE%"].rank(pct=True)  # less negative MAE is better
        )
        best = score.sort_values("综合观察", ascending=False).iloc[0]
        st.success(
            f"当前综合表现最值得继续验证：{best['Stop方案']}。"
            f"平均收益 {best['平均最终收益%']:+.2f}%｜"
            f"胜率 {best['胜率>0']:.1%}｜"
            f"≥5% {best['≥5%']:.1%}｜"
            f"过早退出机会成本 {best['平均过早退出机会成本%']:.2f}%｜"
            f"平均MAE {best['平均路径MAE%']:+.2f}%"
        )

    st.markdown("#### 🔎 逐笔明细")
    cols = [
        "Ticker","BUY时间","BUY类型","BUY价格","初始止损","Stop方案","测试止损","止损距离%",
        "入场15m ATR","退出时间","退出价","退出原因","C退出阶段",
        "最终收益%","路径最高浮盈%","路径MAE%","利润回吐%",
        "峰值保留率%","过早退出机会成本%"
    ]
    cols = [c for c in cols if c in detail.columns]
    st.dataframe(
        detail[cols].style.format({
            "BUY价格":"{:.2f}","初始止损":"{:.2f}","测试止损":"{:.2f}",
            "止损距离%":"{:.2f}","入场15m ATR":"{:.2f}",
            "退出价":"{:.2f}","最终收益%":"{:+.2f}",
            "路径最高浮盈%":"{:+.2f}","路径MAE%":"{:+.2f}",
            "利润回吐%":"{:.2f}","峰值保留率%":"{:.1f}",
            "过早退出机会成本%":"{:.2f}",
        }, na_rep=""),
        hide_index=True,
        use_container_width=True
    )

    csv = detail.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "💾 下载Stop敏感性回测明细",
        csv,
        file_name=f"C_Stop_Sensitivity_{datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )


def render_c_backtest(detail, summary):
    st.subheader("📊 C历史回测结果：卖太早 vs 利润回吐")
    if summary is None or summary.empty:
        st.info("当前日期范围没有产生可比较的历史BUY样本。")
        return

    st.dataframe(
        summary.style.format({
            "平均最终收益%":"{:+.2f}","中位最终收益%":"{:+.2f}",
            "胜率>0":"{:.1%}","≥3%":"{:.1%}","≥5%":"{:.1%}",
            "平均路径最高浮盈%":"{:+.2f}","平均利润回吐%":"{:.2f}",
            "平均峰值保留率%":"{:.1f}","平均过早退出机会成本%":"{:.2f}",
            "STOP/保护退出率":"{:.1%}","TP退出率":"{:.1%}",
        }, na_rep=""),
        hide_index=True,use_container_width=True
    )

    cv = summary[summary["策略"].eq("C 分阶段")]
    if not cv.empty:
        rr = cv.iloc[0]
        c1,c2,c3 = st.columns(3)
        c1.metric("C平均最终收益", f"{safe_float(rr.get('平均最终收益%', np.nan)):+.2f}%")
        c2.metric("C平均过早退出机会成本", f"{safe_float(rr.get('平均过早退出机会成本%', np.nan)):.2f}%")
        c3.metric("C平均利润回吐", f"{safe_float(rr.get('平均利润回吐%', np.nan)):.2f}%")

    st.caption(
        "过早退出机会成本：退出后直到观察窗结束，股票还能达到的最高收益减去实际退出收益；越低越好。"
        "利润回吐：路径最高浮盈减去最终退出收益；越低越好，但不能靠过早卖出把它机械压低。"
    )

    st.markdown("#### 🔎 C v1.3逐笔明细")
    cdetail = detail[detail["策略"].eq("C 分阶段")].copy()
    if not cdetail.empty:
        cols = ["Ticker","BUY时间","BUY类型","BUY价格","初始止损","退出时间","退出价",
                "退出原因","C退出阶段","最终收益%","路径最高浮盈%","利润回吐%",
                "峰值保留率%","过早退出机会成本%"]
        cols = [c for c in cols if c in cdetail.columns]
        st.dataframe(
            cdetail[cols].style.format({
                "BUY价格":"{:.2f}","初始止损":"{:.2f}","退出价":"{:.2f}",
                "最终收益%":"{:+.2f}","路径最高浮盈%":"{:+.2f}",
                "利润回吐%":"{:.2f}","峰值保留率%":"{:.1f}",
                "过早退出机会成本%":"{:.2f}",
            }, na_rep=""),
            hide_index=True,use_container_width=True
        )

    csv = detail.to_csv(index=False).encode("utf-8-sig")
    st.download_button("💾 下载C历史回测明细", csv,
                       file_name=f"C_Backtest_{datetime.now().strftime('%Y-%m-%d')}.csv",
                       mime="text/csv", use_container_width=True)


with st.sidebar:
    st.header("B/C FINAL v1.8 LIVE")
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
        key="bc_final_15m_refresh"
    )
elif auto_monitor and st_autorefresh is None:
    st.warning("请在 requirements.txt 增加：streamlit-autorefresh")

st.info("流程：A FINAL“买”候选 → B用1H确认方向 + 15min找突破/回踩 → BUY / WAIT / AVOID；BUY后的初始Stop使用原止损距离×1.50；实际成交后转入C持仓管理 → HOLD / TP / STOP。")

try:
    a_df,scan_date=load_latest_a_candidates()
except Exception as e:
    st.error(f"读取A候选失败：{e}")
    st.stop()

if a_df.empty:
    st.warning("A最新扫描日没有正式“买”候选，或尚未保存A5.2R FINAL结果。")
    st.stop()

# V1.8 LIVE：A只提供当天候选；B Master累计历史候选并独立计算5交易日有效期。
master_df = load_b_master()
master_df = sync_master_with_a(master_df, a_df, scan_date)
save_b_master(master_df)
monitor_df = active_master_pool(master_df, max_candidates=max_names)

st.success(
    f"A最新扫描日：{scan_date} ｜ B当前监控{len(monitor_df)}只 "
    f"（候选{int((monitor_df.get('池状态','')=='TRACKING').sum()) if not monitor_df.empty else 0}，"
    f"持仓{int((monitor_df.get('池状态','')=='HOLDING').sum()) if not monitor_df.empty else 0}）。"
)

preview=[c for c in ["Ticker","池状态","是否持仓","A5决策","空间等级","空间优先级","上方空间","首次进入B","最近入选日期","跟踪天数","观察剩余天数","Rank","共振数","Company","Early V2 Score","Confidence"] if c in monitor_df.columns]
if preview and not monitor_df.empty:
    st.dataframe(monitor_df[preview],hide_index=True,use_container_width=True)

with st.expander("💼 持仓管理（只有实际买入后才标记）", expanded=False):
    st.caption("B出现BUY只是程序买点信号，不代表你已经买入。V1.8的“参考止损”已按原止损距离×1.50放宽；只有你实际成交后，才在这里标记为持仓。你仍可按真实成交情况手动调整持仓止损。")
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

    order={"🛑 STOP LOSS":0,"🔻 PROFIT PROTECT":1,"🟣 TAKE PROFIT TP2":2,"🟠 TAKE PROFIT TP1":3,"🟢 BUY":4,"🟠 EARLY BUY":5,"🟡 HOLD / 趋势转弱":6,"🟢 HOLD":7,"🟡 WAIT":8,"🔴 AVOID":9,"⚪ DATA":10}
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
            # C状态持续写回Master，方便下一轮和人工复核。
            is_hold = mm.loc[mask,"是否持仓"].astype(str).isin(["是","Y","YES","TRUE","1"]).any() if "是否持仓" in mm.columns else False
            if is_hold:
                for _c in ["C阶段","持仓最高价","最高浮盈%","动态保护价","利润回吐%"]:
                    if _c in rr.index:
                        mm.loc[mask,_c] = rr.get(_c,"")
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
    "🎯 立即运行 B/C 盘中检查",
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
    st.subheader("📡 B/C FINAL 盘中结果")
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

    c_actions = out[out["盘中决策"].isin(["🛑 STOP LOSS","🔻 PROFIT PROTECT","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"])]
    if not c_actions.empty:
        st.error(
            "🚨 C持仓处理提醒：" +
            "；".join(c_actions.apply(lambda r: f"{r['Ticker']} {r['盘中决策']}", axis=1).tolist())
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
        actions = out.loc[out["盘中决策"].isin(["🛑 STOP LOSS","🔻 PROFIT PROTECT","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"]),"Ticker"].astype(str).tolist()
        waits = out.loc[out["盘中决策"]=="🟡 WAIT","Ticker"].astype(str).tolist()
        avoids = out.loc[out["盘中决策"]=="🔴 AVOID","Ticker"].astype(str).tolist()
        text = f"🔔 两小时状态提醒｜BUY {len(buys)} ｜ EARLY {len(early)} ｜ HOLD {len(holds)} ｜ TP/STOP {len(actions)}"
        if buys:
            text += " ｜ BUY：" + ", ".join(buys)
        if actions:
            text += " ｜ 需处理：" + ", ".join(actions)
        text += f" ｜ WAIT {len(waits)} ｜ AVOID {len(avoids)}"
        st.info(text)
    # Streamlit/Pandas Styler requires numeric values for numeric format strings.
    # Google Sheet may return values as text (e.g. "+3.4%", "None"), so normalize first.
    out_display = out.copy()
    if "A上方空间" in out_display.columns:
        out_display["A上方空间"] = out_display["A上方空间"].apply(safe_percent_value)

    numeric_display_cols = [
        "当前价格","持仓成本","持仓盈亏%","1H RSI",
        "15m VWAP","15m EMA9","15m EMA20","15m RSI","15m量比",
        "突破幅度%","参考入场","基础止损","参考止损","TP1","TP2",
        "持仓最高价","最高浮盈%","动态保护价","利润回吐%"
    ]
    for _c in numeric_display_cols:
        if _c in out_display.columns:
            out_display[_c] = pd.to_numeric(out_display[_c], errors="coerce")

    fmt={"A上方空间":"{:+.1%}","当前价格":"{:.2f}","持仓成本":"{:.2f}","持仓盈亏%":"{:.2f}","持仓最高价":"{:.2f}","最高浮盈%":"{:.2f}","动态保护价":"{:.2f}","利润回吐%":"{:.2f}","1H RSI":"{:.1f}","15m VWAP":"{:.2f}","15m EMA9":"{:.2f}","15m EMA20":"{:.2f}","15m RSI":"{:.1f}","15m量比":"{:.2f}","突破幅度%":"{:.2f}","参考入场":"{:.2f}","基础止损":"{:.2f}","参考止损":"{:.2f}","TP1":"{:.2f}","TP2":"{:.2f}"}
    display_out = chinese_sheet_columns(out_display)
    fmt_cn = {B_DISPLAY_CN_MAP.get(k,k):v for k,v in fmt.items()}
    st.dataframe(
        display_out.style.format(
            {k:v for k,v in fmt_cn.items() if k in display_out.columns},
            na_rep=""
        ),
        hide_index=True,
        use_container_width=True
    )


    holdings_view = out[out["池状态"].astype(str).eq("HOLDING")].copy() if "池状态" in out.columns else pd.DataFrame()
    if not holdings_view.empty:
        st.subheader("🛡️ C 持仓退出管理")
        c_cols = [
            "Ticker","盘中决策","C阶段","持仓成本","当前价格","持仓盈亏%",
            "持仓最高价","最高浮盈%","利润回吐%","动态保护价",
            "参考止损","TP1","TP2","趋势转弱警报","决策依据"
        ]
        c_cols = [c for c in c_cols if c in holdings_view.columns]
        c_show = holdings_view[c_cols].copy()
        st.dataframe(
            c_show.style.format({
                "持仓成本":"{:.2f}","当前价格":"{:.2f}","持仓盈亏%":"{:.2f}",
                "持仓最高价":"{:.2f}","最高浮盈%":"{:.2f}",
                "利润回吐%":"{:.2f}","动态保护价":"{:.2f}",
                "参考止损":"{:.2f}","TP1":"{:.2f}","TP2":"{:.2f}"
            }, na_rep=""),
            hide_index=True,
            use_container_width=True
        )
        st.caption("C分阶段保护不会在+1%/+2%就抬止损。峰值未到+4%仍使用原始止损；之后才逐级保护利润。")

    st.subheader("🧪 BUY条件诊断")
    diag_cols = [
        "Ticker","盘中决策","BUY门槛诊断","1H状态","1H强","1H至少中等",
        "VWAP上方","15m突破","接近突破位","15m回踩",
        "15m EMA结构","15m MACD正","15m MACD改善",
        "突破RSI合格","突破量比≥1.50","回踩量比≥0.80","突破不追高",
        "15m RSI","15m量比"
    ]
    diag_cols = [c for c in diag_cols if c in out.columns]
    diag_show = out[diag_cols].copy()
    if not diag_show.empty:
        st.dataframe(
            diag_show.style.format({
                "15m RSI":"{:.1f}",
                "15m量比":"{:.2f}",
            }, na_rep=""),
            hide_index=True,
            use_container_width=True
        )
        st.caption("这张表只做诊断，不改变当前BUY/WAIT/EARLY逻辑。重点看EARLY/WAIT到底缺的是突破、量比、1H、VWAP、MACD还是RSI。")

    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric("🟢 BUY",int((out["盘中决策"]=="🟢 BUY").sum()))
    c2.metric("🟠 EARLY",int((out["盘中决策"]=="🟠 EARLY BUY").sum()))
    c3.metric("🟢 HOLD",int((out["盘中决策"]=="🟢 HOLD").sum()))
    c4.metric("🟡 WAIT",int((out["盘中决策"]=="🟡 WAIT").sum()))
    c5.metric("🛑 TP/STOP",int(out["盘中决策"].isin(["🛑 STOP LOSS","🔻 PROFIT PROTECT","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"]).sum()))

    csv=chinese_sheet_columns(out).to_csv(index=False).encode("utf-8-sig")
    st.download_button("💾 下载盘中结果",csv,
        file_name=f"B_Intraday_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv",
        mime="text/csv",use_container_width=True)

st.divider()
with st.expander("📘 查看 B/C FINAL v1.8 LIVE 最终规则", expanded=False):
    st.markdown(
        """
### B：盘中买点
- 只跟踪 A FINAL 最新正式判定为“买”的候选，以及已经标记为真实持仓的股票。
- 候选进入 `B_MasterList` 后最多跟踪约 5 个交易日；真实持仓不受这个期限限制。
- 1H 确认方向与动量；15min 判断突破 / 回踩 / VWAP / EMA / MACD / RSI / 量比。
- 正式 BUY 仍使用已经验证过的原有 B 条件；本版**不改变 BUY 门槛**。
- `EARLY BUY` 只是临近买点，不等于正式 BUY。

### V1.8 最终初始 Stop
- B 原来的基础 Stop 结构保持不变。
- 正式交给持仓管理的 `参考止损` = **原止损距离 × 1.50**。
- 例如：参考入场 100，旧基础 Stop 99，则 V1.8 参考止损为 98.50。
- 这是历史稳定性测试后唯一正式写入 LIVE 的 Stop 改动。
- `基础止损` 仅保留作诊断；实盘默认看 `参考止损`。

### C：真实持仓退出
- 只有你实际买入并在“持仓管理”里标记后，C 才接管。
- C0：最高浮盈 <4%，保持初始 Stop，不因普通 +1%/+2% 波动抬止损。
- C1：最高浮盈 4%–6%，保护到接近保本（约买入价 -0.25%）。
- C2：最高浮盈 6%–10%，至少保护 +2%，或保留最高浮盈的 40%，取更高者。
- C3：最高浮盈 ≥10%，至少保护 +4%，或保留最高浮盈的 60%，取更高者。
- TP1 为分批止盈提醒；TP2 为更强止盈提醒。
- 趋势转弱首先作为警报，不因普通回撤自动清仓。

### 运行
- App 打开且处于正常交易时段时，每 15 分钟检查一次。
- Streamlit Cloud 在无人访问时不保证持续后台运行。
- `B_Log` 记录每轮检查；`B_MasterList` 保存候选、持仓和 C 状态。
        """
    )

st.success("✅ B/C FINAL v1.8 LIVE 已定型：B买点逻辑不变，初始Stop正式采用1.50×距离，C分阶段保护保持不变。")

