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

st.set_page_config(page_title="CMS V4.3B V2.3 — Profit Giveback Test", page_icon="🎯", layout="wide")
st.title("🎯 CMS Stock Screener V4.3B V2.3 — 3日涨幅与利润回吐测试")
st.caption("V2.2先测试“突破后等待确认”，暂不把等待逻辑放进LIVE。LIVE仍沿用V2.1；回踩BUY和B Master累计逻辑不变。")

A_WORKSHEET = "A_Candidates"
B_LOG_WORKSHEET = "B_Log"
B_MASTER_WORKSHEET = "B_MasterList"

SHEET_CN_MAP = {'Scan Date': '扫描日期', 'Scan Time': '扫描时间', 'Ticker': '股票代码', 'Company': '公司', 'Sector': '板块', 'Market Cap': '市值', 'Price': '价格', 'ATR14': 'ATR14', 'RVOL': 'RVOL', 'Dollar Volume': '成交额', '5D Return': '5日涨跌幅', '20D Return': '20日涨跌幅', 'Rank': '排名', 'Early V2 Score': 'Early V2总分', 'Confidence': '信心等级', 'Fundamental Confirmation': '基本面确认', 'Fundamental Reason': '基本面依据', 'Quality Fundamental': '质量', 'FCF Fundamental': '现金流', 'Debt Fundamental': '负债', 'Valuation Fundamental': '估值', 'Growth Fundamental': '增长', 'ROE': 'ROE', 'Operating Margin': '营业利润率', 'Free Cash Flow': '自由现金流', 'Operating Cash Flow': '经营现金流', 'Debt to Equity': 'Debt/Equity', 'Forward PE': 'Forward P/E', 'PEG': 'PEG', 'EV/EBITDA': 'EV/EBITDA', 'Revenue Growth': '营收增长', 'Earnings Growth': '盈利增长', 'Structure Score': '市场结构分', 'Trend & Momentum Score': '趋势动量分', 'Accumulation Score': '资金积累分', 'Leadership Score': '相对强势分', 'Catalyst Score': '催化剂分', 'Major Resistance Zone': '主要压力区', 'Resistance Touches': '压力测试次数', 'Resistance Strength': '压力强度', 'Major Support Zone': '主要支撑区', 'Support Touches': '支撑测试次数', 'Short-term Breakout': '短期突破位', 'Distance to Major Resistance': '距主要压力', 'Distance to Short Breakout': '距短期突破', 'Compression Ratio': '压缩比', 'R→S Flip': 'R→S转换', 'R→S Flip Zone': 'R→S回踩区', 'R→S Flip Touches': 'R→S历史测试次数', 'MA20': 'MA20', 'MA50': 'MA50', 'MA200': 'MA200', 'MA20 Slope 5D': 'MA20 5日斜率', 'MACD': 'MACD', 'MACD Signal': 'MACD信号', 'MACD Histogram': 'MACD柱', 'MACD Phase': 'MACD阶段', 'RSI14': 'RSI14', 'Volume Build Ratio': '量能增强比', 'Up/Down Volume Ratio': '涨跌量比', 'OBV Trend': 'OBV趋势', 'OBV Positive Divergence': 'OBV正背离', 'Stock vs SPY 20D': '个股 vs SPY 20日', 'Sector vs SPY 20D': '板块 vs SPY 20日', 'Stock vs Sector 20D': '个股 vs 板块 20日', 'Stock vs SPY 5D': '个股 vs SPY 5日', 'RS Acceleration': 'RS加速度', 'Sector ETF': '板块ETF', 'Catalyst Label': '催化剂状态', 'Positive Catalyst': '正面催化剂', 'Negative Catalyst': '负面催化剂', 'Headlines': '相关新闻', 'Hard Filter': '硬筛选', 'Hard Filter Reason': '硬筛选原因', 'CMS Context': 'CMS参考'}
SHEET_INTERNAL_MAP = {v:k for k,v in SHEET_CN_MAP.items()}
B_DISPLAY_CN_MAP = {**SHEET_CN_MAP, "Ticker":"股票代码", "Company":"公司", "Rank":"排名", "Confidence":"信心等级", "Fundamental Confirmation":"基本面确认", "Early V2 Score":"Early V2总分"}
B_MASTER_PRIMARY = ["Ticker","Company","池状态","是否持仓","最后决策","最后价格","实际买入价","持仓止损","TP1","TP2","最近入选日期","跟踪天数","观察剩余天数","最后检查时间","最后决策依据","Rank","Early V2 Score","Confidence","Fundamental Confirmation","首次进入B","最近同步A","实际买入日期","退出日期","退出价","退出原因"]

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
    st.header("V4.3B V2.3 参数")
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

# V1.6关键变化：A只提供当天候选；B Master负责累计历史候选并独立计算5交易日有效期。
master_df = load_b_master()
master_df = sync_master_with_a(master_df, a_df, scan_date)
save_b_master(master_df)
monitor_df = active_master_pool(master_df, max_candidates=max_names)

st.success(
    f"A最新扫描日：{scan_date} ｜ B当前监控{len(monitor_df)}只 "
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
    fmt={"当前价格":"{:.2f}","持仓成本":"{:.2f}","持仓盈亏%":"{:.2f}","1H RSI":"{:.1f}","15m VWAP":"{:.2f}","15m EMA9":"{:.2f}","15m EMA20":"{:.2f}","15m RSI":"{:.1f}","15m量比":"{:.2f}","突破幅度%":"{:.2f}","参考入场":"{:.2f}","参考止损":"{:.2f}","TP1":"{:.2f}","TP2":"{:.2f}"}
    display_out = chinese_sheet_columns(out)
    fmt_cn = {B_DISPLAY_CN_MAP.get(k,k):v for k,v in fmt.items()}
    st.dataframe(display_out.style.format({k:v for k,v in fmt_cn.items() if k in display_out.columns},na_rep=""),hide_index=True,use_container_width=True)

    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric("🟢 BUY",int((out["盘中决策"]=="🟢 BUY").sum()))
    c2.metric("🟠 EARLY",int((out["盘中决策"]=="🟠 EARLY BUY").sum()))
    c3.metric("🟢 HOLD",int((out["盘中决策"]=="🟢 HOLD").sum()))
    c4.metric("🟡 WAIT",int((out["盘中决策"]=="🟡 WAIT").sum()))
    c5.metric("🛑 TP/STOP",int(out["盘中决策"].isin(["🛑 STOP LOSS","🟣 TAKE PROFIT TP2","🟠 TAKE PROFIT TP1"]).sum()))

    csv=chinese_sheet_columns(out).to_csv(index=False).encode("utf-8-sig")
    st.download_button("💾 下载盘中结果",csv,
        file_name=f"B_Intraday_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv",
        mime="text/csv",use_container_width=True)




def _future_bar_metrics(m15_all, signal_ts, entry_price, bars_ahead):
    """BUY之后固定15m根数的收益；若数据不足返回NaN。"""
    if m15_all is None or m15_all.empty or pd.isna(entry_price) or entry_price <= 0:
        return np.nan
    fut = m15_all[m15_all.index > signal_ts]
    if len(fut) < bars_ahead:
        return np.nan
    px = safe_float(fut.iloc[bars_ahead - 1]["Close"])
    return ((px - entry_price) / entry_price * 100) if not pd.isna(px) else np.nan


def _future_window_excursions(m15_all, signal_ts, entry_price, bars_ahead):
    """BUY后指定窗口的最大有利涨幅(MFE)和最大不利回撤(MAE)。"""
    if m15_all is None or m15_all.empty or pd.isna(entry_price) or entry_price <= 0:
        return np.nan, np.nan
    fut = m15_all[m15_all.index > signal_ts].head(bars_ahead)
    if fut.empty:
        return np.nan, np.nan
    hi = pd.to_numeric(fut["High"], errors="coerce").max()
    lo = pd.to_numeric(fut["Low"], errors="coerce").min()
    mfe = ((hi - entry_price) / entry_price * 100) if not pd.isna(hi) else np.nan
    mae = ((lo - entry_price) / entry_price * 100) if not pd.isna(lo) else np.nan
    return mfe, mae


def buy_quality_replay(row, start_date, end_date):
    """
    找出BUY状态“首次切入”的时点，并评估后续表现。
    1小时=4根15m；当日收盘=同交易日最后一根；1/3交易日用后续交易日收盘。
    """
    ticker = str(row["Ticker"]).strip().upper()
    m15_all = get_replay_intraday(ticker, "15m", start_date, end_date)
    h1_all = get_replay_intraday(ticker, "60m", start_date, end_date)

    if m15_all is None or m15_all.empty or h1_all is None or h1_all.empty:
        return pd.DataFrame()

    start_ts = pd.Timestamp(start_date).tz_localize(MARKET_TZ)
    end_ts = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize(MARKET_TZ)
    bars = m15_all[(m15_all.index >= start_ts) & (m15_all.index < end_ts)].copy()
    if bars.empty:
        return pd.DataFrame()

    signals = []
    prev_state = None

    for ts in bars.index:
        m15_slice = m15_all[m15_all.index <= ts]
        h1_slice = h1_all[h1_all.index <= ts]
        h1 = evaluate_1h(h1_slice)
        m15 = evaluate_15m(m15_slice)
        if not h1.get("valid") or not m15.get("valid"):
            continue

        d, reason, entry, stop = decision(row, h1, m15)

        # 只把从非BUY切换到BUY的那一刻当作一次BUY信号，避免连续BUY重复计算。
        if d == "🟢 BUY" and prev_state != "🟢 BUY":
            entry_px = safe_float(m15.get("price", entry))
            signal_date = ts.date()

            # 1小时后
            ret_1h = _future_bar_metrics(m15_all, ts, entry_px, 4)

            # 当日收盘
            same_day = m15_all[(m15_all.index.date == signal_date) & (m15_all.index > ts)]
            close_day = safe_float(same_day.iloc[-1]["Close"]) if not same_day.empty else entry_px
            ret_close = ((close_day-entry_px)/entry_px*100) if entry_px > 0 else np.nan

            # 后续交易日收盘
            later = m15_all[m15_all.index.date > signal_date].copy()
            later_dates = sorted(set(later.index.date))
            ret_1d = np.nan
            ret_3d = np.nan
            if len(later_dates) >= 1:
                d1 = later[later.index.date == later_dates[0]]
                p1 = safe_float(d1.iloc[-1]["Close"]) if not d1.empty else np.nan
                if not pd.isna(p1):
                    ret_1d = (p1-entry_px)/entry_px*100
            if len(later_dates) >= 3:
                d3 = later[later.index.date == later_dates[2]]
                p3 = safe_float(d3.iloc[-1]["Close"]) if not d3.empty else np.nan
                if not pd.isna(p3):
                    ret_3d = (p3-entry_px)/entry_px*100

            # 未来约1交易日(26根15m)和3交易日(78根15m)的MFE/MAE
            mfe_1d, mae_1d = _future_window_excursions(m15_all, ts, entry_px, 26)
            mfe_3d, mae_3d = _future_window_excursions(m15_all, ts, entry_px, 78)

            signals.append({
                "股票代码": ticker,
                "BUY时间": ts.strftime("%Y-%m-%d %H:%M"),
                "BUY价格": entry_px,
                "BUY类型": "突破" if m15.get("breakout") else ("回踩" if m15.get("pullback") else "其他"),
                "1H状态": h1.get("status",""),
                "15m量比": safe_float(m15.get("volratio",np.nan)),
                "1小时后%": ret_1h,
                "当日收盘%": ret_close,
                "下一交易日收盘%": ret_1d,
                "3交易日收盘%": ret_3d,
                "1日最大涨幅%": mfe_1d,
                "1日最大回撤%": mae_1d,
                "3日最大涨幅%": mfe_3d,
                "3日最大回撤%": mae_3d,
                "参考止损": stop,
                "触发依据": reason
            })

        prev_state = d

    return pd.DataFrame(signals)


def run_buy_quality_batch(master_df, tickers, start_date, end_date):
    all_parts = []
    prog = st.progress(0)
    msg = st.empty()
    for i, ticker in enumerate(tickers, 1):
        msg.write(f"验证BUY质量 {ticker} ({i}/{len(tickers)})")
        rr = master_df[master_df["Ticker"].astype(str).str.upper().eq(str(ticker).upper())]
        if not rr.empty:
            part = buy_quality_replay(rr.iloc[-1], start_date, end_date)
            if part is not None and not part.empty:
                all_parts.append(part)
        prog.progress(int(i / len(tickers) * 100))
    msg.empty()
    prog.empty()
    return pd.concat(all_parts, ignore_index=True) if all_parts else pd.DataFrame()


def diagnose_replay_ticker(row, start_date, end_date):
    """批量诊断：统计每个BUY门槛在历史15m时点满足了多少次，以及主要阻挡条件。"""
    ticker = str(row["Ticker"]).strip().upper()
    m15_all = get_replay_intraday(ticker, "15m", start_date, end_date)
    h1_all = get_replay_intraday(ticker, "60m", start_date, end_date)

    if m15_all is None or m15_all.empty or h1_all is None or h1_all.empty:
        return {
            "股票代码": ticker, "有效K线": 0, "BUY次数": 0, "EARLY次数": 0,
            "1H强/中等": 0, "VWAP上方": 0, "MACD改善": 0,
            "量比≥1.20": 0, "量比≥0.80": 0, "15m突破": 0, "15m回踩": 0,
            "主要阻挡": "历史数据不足"
        }

    start_ts = pd.Timestamp(start_date).tz_localize(MARKET_TZ)
    end_ts = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize(MARKET_TZ)
    bars = m15_all[(m15_all.index >= start_ts) & (m15_all.index < end_ts)].copy()

    counts = {
        "有效K线":0, "BUY次数":0, "EARLY次数":0,
        "1H强/中等":0, "VWAP上方":0, "MACD改善":0,
        "量比≥1.20":0, "量比≥0.80":0, "15m突破":0, "15m回踩":0
    }
    blockers = {
        "1H趋势不足":0, "VWAP下方":0, "MACD未改善":0,
        "量能不足":0, "缺突破/回踩":0, "基本面/信心偏弱":0, "追高过滤":0
    }

    prev_state = None
    buy_transitions = 0
    early_transitions = 0

    for ts in bars.index:
        m15_slice = m15_all[m15_all.index <= ts]
        h1_slice = h1_all[h1_all.index <= ts]
        h1 = evaluate_1h(h1_slice)
        m15 = evaluate_15m(m15_slice)

        if not h1.get("valid") or not m15.get("valid"):
            continue

        counts["有效K线"] += 1
        if h1.get("status") in ["强","中等"]:
            counts["1H强/中等"] += 1
        if m15.get("above_vwap"):
            counts["VWAP上方"] += 1
        if m15.get("macd_improving"):
            counts["MACD改善"] += 1
        vr = safe_float(m15.get("volratio", np.nan))
        if not pd.isna(vr) and vr >= 1.20:
            counts["量比≥1.20"] += 1
        if not pd.isna(vr) and vr >= 0.80:
            counts["量比≥0.80"] += 1
        if m15.get("breakout"):
            counts["15m突破"] += 1
        if m15.get("pullback"):
            counts["15m回踩"] += 1

        d, _, _, _ = decision(row, h1, m15)
        if d == "🟢 BUY" and prev_state != "🟢 BUY":
            buy_transitions += 1
        if d == "🟠 EARLY BUY" and prev_state != "🟠 EARLY BUY":
            early_transitions += 1
        prev_state = d

        # 诊断“为什么没有BUY”，按当前B逻辑的门槛顺序统计。
        if h1.get("status") == "弱":
            blockers["1H趋势不足"] += 1
            continue
        if m15.get("overextended"):
            blockers["追高过滤"] += 1
            continue
        if not m15.get("above_vwap"):
            blockers["VWAP下方"] += 1
            continue
        if weak_fundamental(row):
            blockers["基本面/信心偏弱"] += 1
            continue
        if not m15.get("macd_improving"):
            blockers["MACD未改善"] += 1
            continue

        breakout_path = bool(m15.get("breakout"))
        pullback_path = bool(m15.get("pullback"))
        if not breakout_path and not pullback_path:
            blockers["缺突破/回踩"] += 1
        elif breakout_path and (pd.isna(vr) or vr < 1.20) and not pullback_path:
            blockers["量能不足"] += 1
        elif pullback_path and (not pd.isna(vr) and vr < 0.80) and not breakout_path:
            blockers["量能不足"] += 1

    counts["BUY次数"] = buy_transitions
    counts["EARLY次数"] = early_transitions

    if counts["有效K线"] == 0:
        main_block = "无有效K线"
    else:
        max_block = max(blockers.values()) if blockers else 0
        main_block = max(blockers, key=blockers.get) if max_block > 0 else "条件总体通过"

    return {"股票代码":ticker, **counts, "主要阻挡":main_block}


def run_batch_replay(master_df, tickers, start_date, end_date):
    rows = []
    prog = st.progress(0)
    msg = st.empty()
    for i, ticker in enumerate(tickers, 1):
        msg.write(f"批量诊断 {ticker} ({i}/{len(tickers)})")
        rr = master_df[master_df["Ticker"].astype(str).str.upper().eq(str(ticker).upper())]
        if not rr.empty:
            rows.append(diagnose_replay_ticker(rr.iloc[-1], start_date, end_date))
        prog.progress(int(i / len(tickers) * 100))
    msg.empty()
    prog.empty()
    return pd.DataFrame(rows)


st.divider()
st.subheader("🧪 历史 REPLAY 测试")
st.caption(
    "不影响LIVE、不写入B_Log、不修改B_MasterList。"
    "选择Master中的股票和过去日期后，程序会用同一套B判断逻辑逐根回放15分钟K线，只显示状态变化。"
)


st.markdown("### 🔬 一键批量诊断当前B候选")
range_choice = st.selectbox(
    "批量回放范围",
    ["最近10个交易日", "最近20个交易日", "最近30个交易日", "自定义"],
    index=2,
    help="建议优先用最近30个交易日积累更多BUY样本。Yahoo 15分钟历史数据范围有限。"
)

range_map = {
    "最近10个交易日": 14,
    "最近20个交易日": 28,
    "最近30个交易日": 42
}

bc1, bc2 = st.columns(2)
batch_end = bc2.date_input(
    "批量结束日期",
    value=market_now().date(),
    max_value=market_now().date(),
    key="batch_replay_end"
)

if range_choice == "自定义":
    batch_default_start = batch_end - pd.Timedelta(days=35)
else:
    batch_default_start = batch_end - pd.Timedelta(days=range_map[range_choice])

batch_start = bc1.date_input(
    "批量开始日期",
    value=batch_default_start.date() if hasattr(batch_default_start, "date") else batch_default_start,
    max_value=batch_end,
    key=f"batch_replay_start_{range_choice}"
)

st.caption("推荐：先用最近30个交易日。若15分钟数据下载失败，再缩短为20个交易日。")

batch_tickers = (
    monitor_df["Ticker"].astype(str).dropna().drop_duplicates().tolist()
    if monitor_df is not None and not monitor_df.empty and "Ticker" in monitor_df.columns
    else []
)

if st.button("🔬 一键诊断当前B监控股票", type="primary", use_container_width=True):
    if batch_start > batch_end:
        st.error("开始日期不能晚于结束日期。")
    elif not batch_tickers:
        st.warning("当前B没有可诊断股票。")
    else:
        with st.spinner("正在批量回放并诊断BUY门槛..."):
            batch_out = run_batch_replay(master_df, batch_tickers, batch_start, batch_end)

        if batch_out.empty:
            st.warning("没有得到批量诊断结果。")
        else:
            total_buy = int(batch_out["BUY次数"].sum())
            total_early = int(batch_out["EARLY次数"].sum())
            names_with_buy = int((batch_out["BUY次数"] > 0).sum())
            names_with_early = int((batch_out["EARLY次数"] > 0).sum())

            st.success(
                f"批量诊断完成：{len(batch_out)}只 ｜ "
                f"出现BUY的股票 {names_with_buy}只 / BUY状态变化 {total_buy}次 ｜ "
                f"出现EARLY的股票 {names_with_early}只 / EARLY状态变化 {total_early}次"
            )

            st.dataframe(batch_out, hide_index=True, use_container_width=True)

            if names_with_buy == 0:
                st.warning("⚠️ 当前样本没有任何BUY。先看“主要阻挡”和各门槛通过次数，再决定是否放松参数。")
            elif names_with_buy <= max(1, len(batch_out)//5):
                st.info("BUY触发较少，系统可能偏严格；建议结合主要阻挡列判断具体该调哪一关。")
            else:
                st.info("已有多只股票产生BUY，暂不建议整体放松条件，应优先检查BUY后的表现。")

            batch_csv = batch_out.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "💾 下载批量诊断结果",
                batch_csv,
                file_name=f"B_Batch_Diagnostic_{batch_start}_{batch_end}.csv",
                mime="text/csv",
                use_container_width=True
            )




def original_v20_breakout_trigger(row, h1, m15):
    """V2.0原始突破BUY门槛，仅用于历史测试；不改变LIVE。"""
    if not h1.get("valid") or not m15.get("valid"):
        return False
    if h1.get("status") == "弱":
        return False
    if m15.get("overextended"):
        return False
    if not m15.get("above_vwap"):
        return False
    if weak_fundamental(row):
        return False
    vr = safe_float(m15.get("volratio", np.nan))
    return (
        h1.get("status") == "强"
        and bool(m15.get("breakout"))
        and bool(m15.get("ema_structure"))
        and bool(m15.get("macd_improving"))
        and not pd.isna(vr)
        and vr >= 1.20
    )



def day_high_close_metrics(m15_all, entry_ts, entry_px, nth_day):
    """第nth个交易日（1=买入当日）的最高涨幅和收盘收益。"""
    dates = sorted(set(m15_all[m15_all.index >= entry_ts].index.date))
    if len(dates) < nth_day:
        return np.nan, np.nan
    d = dates[nth_day-1]
    x = m15_all[m15_all.index.date == d]
    if nth_day == 1:
        x = x[x.index >= entry_ts]
    if x.empty or pd.isna(entry_px) or entry_px <= 0:
        return np.nan, np.nan
    hi = pd.to_numeric(x["High"], errors="coerce").max()
    close = safe_float(x.iloc[-1]["Close"])
    high_ret = (hi-entry_px)/entry_px*100 if not pd.isna(hi) else np.nan
    close_ret = (close-entry_px)/entry_px*100 if not pd.isna(close) else np.nan
    return high_ret, close_ret


def three_day_giveback_metrics(m15_all, entry_ts, entry_px):
    """
    从BUY到第3个交易日结束：
    peak_ret = 期间最高浮盈%
    end_ret = 第3日收盘收益%
    giveback = 最高浮盈 - 第3日收盘收益
    """
    dates = sorted(set(m15_all[m15_all.index >= entry_ts].index.date))
    if not dates:
        return np.nan, np.nan, np.nan
    use_dates = dates[:3]
    x = m15_all[m15_all.index.date.astype(object).isin(use_dates)]
    x = x[x.index >= entry_ts]
    if x.empty or pd.isna(entry_px) or entry_px <= 0:
        return np.nan, np.nan, np.nan
    hi = pd.to_numeric(x["High"], errors="coerce").max()
    peak_ret = (hi-entry_px)/entry_px*100 if not pd.isna(hi) else np.nan
    last_close = safe_float(x.iloc[-1]["Close"])
    end_ret = (last_close-entry_px)/entry_px*100 if not pd.isna(last_close) else np.nan
    giveback = peak_ret-end_ret if not pd.isna(peak_ret) and not pd.isna(end_ret) else np.nan
    return peak_ret, end_ret, giveback


def breakout_confirmation_test(row, start_date, end_date):
    """
    对V2.0原始突破信号测试：
    A) 突破当刻立即买
    B) 等30分钟(2根15m)后，若仍站在原突破位和VWAP上方、1H非弱，则买
    C) 等60分钟(4根15m)后，同样确认后再买
    """
    ticker = str(row["Ticker"]).strip().upper()
    m15_all = get_replay_intraday(ticker, "15m", start_date, end_date)
    h1_all = get_replay_intraday(ticker, "60m", start_date, end_date)
    if m15_all is None or m15_all.empty or h1_all is None or h1_all.empty:
        return pd.DataFrame()

    start_ts = pd.Timestamp(start_date).tz_localize(MARKET_TZ)
    end_ts = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize(MARKET_TZ)
    bars = m15_all[(m15_all.index >= start_ts) & (m15_all.index < end_ts)].copy()
    if bars.empty:
        return pd.DataFrame()

    events = []
    prev_trigger = False

    for ts in bars.index:
        m15_slice = m15_all[m15_all.index <= ts]
        h1_slice = h1_all[h1_all.index <= ts]
        h1 = evaluate_1h(h1_slice)
        m15 = evaluate_15m(m15_slice)
        trig = original_v20_breakout_trigger(row, h1, m15)

        # Only count a new breakout episode once.
        if trig and not prev_trigger:
            signal_px = safe_float(m15.get("price", np.nan))
            # Original breakout level = prior 20-bar high.
            prior = m15_all[m15_all.index < ts].tail(20)
            breakout_level = pd.to_numeric(prior["High"], errors="coerce").max() if not prior.empty else np.nan

            for label, wait_bars in [("立即买",0), ("等30分钟确认",2), ("等60分钟确认",4)]:
                if wait_bars == 0:
                    entry_ts = ts
                    entry_px = signal_px
                    confirmed = True
                else:
                    fut = m15_all[m15_all.index > ts]
                    if len(fut) < wait_bars:
                        continue
                    entry_ts = fut.index[wait_bars-1]

                    # Do not confirm on a later calendar day.
                    if entry_ts.date() != ts.date():
                        continue

                    entry_slice = m15_all[m15_all.index <= entry_ts]
                    h1_entry_slice = h1_all[h1_all.index <= entry_ts]
                    em15 = evaluate_15m(entry_slice)
                    eh1 = evaluate_1h(h1_entry_slice)
                    entry_px = safe_float(em15.get("price", np.nan))

                    # Confirmation = breakout has held, still above VWAP, 1H trend not broken.
                    confirmed = (
                        em15.get("valid")
                        and eh1.get("valid")
                        and eh1.get("status") in ["强","中等"]
                        and em15.get("above_vwap")
                        and not pd.isna(entry_px)
                        and not pd.isna(breakout_level)
                        and entry_px >= breakout_level
                    )

                if not confirmed or pd.isna(entry_px) or entry_px <= 0:
                    continue

                ret_1h = _future_bar_metrics(m15_all, entry_ts, entry_px, 4)

                same_day = m15_all[(m15_all.index.date == entry_ts.date()) & (m15_all.index > entry_ts)]
                close_day = safe_float(same_day.iloc[-1]["Close"]) if not same_day.empty else entry_px
                ret_close = ((close_day-entry_px)/entry_px*100) if entry_px > 0 else np.nan

                later = m15_all[m15_all.index.date > entry_ts.date()].copy()
                later_dates = sorted(set(later.index.date))
                ret_1d = np.nan
                ret_3d = np.nan
                if len(later_dates) >= 1:
                    d1 = later[later.index.date == later_dates[0]]
                    p1 = safe_float(d1.iloc[-1]["Close"]) if not d1.empty else np.nan
                    if not pd.isna(p1):
                        ret_1d = (p1-entry_px)/entry_px*100
                if len(later_dates) >= 3:
                    d3 = later[later.index.date == later_dates[2]]
                    p3 = safe_float(d3.iloc[-1]["Close"]) if not d3.empty else np.nan
                    if not pd.isna(p3):
                        ret_3d = (p3-entry_px)/entry_px*100

                mfe1, mae1 = _future_window_excursions(m15_all, entry_ts, entry_px, 26)
                d1_high, d1_close = day_high_close_metrics(m15_all, entry_ts, entry_px, 1)
                d2_high, d2_close = day_high_close_metrics(m15_all, entry_ts, entry_px, 2)
                d3_high, d3_close = day_high_close_metrics(m15_all, entry_ts, entry_px, 3)
                peak3, end3, giveback3 = three_day_giveback_metrics(m15_all, entry_ts, entry_px)
                events.append({
                    "股票代码": ticker,
                    "原突破时间": ts.strftime("%Y-%m-%d %H:%M"),
                    "策略": label,
                    "确认买入时间": entry_ts.strftime("%Y-%m-%d %H:%M"),
                    "买入价格": entry_px,
                    "1小时后%": ret_1h,
                    "当日收盘%": ret_close,
                    "下一交易日%": ret_1d,
                    "3交易日%": ret_3d,
                    "第1日最高涨幅%": d1_high,
                    "第1日收盘收益%": d1_close,
                    "第2日最高涨幅%": d2_high,
                    "第2日收盘收益%": d2_close,
                    "第3日最高涨幅%": d3_high,
                    "第3日收盘收益%": d3_close,
                    "3日内最高浮盈%": peak3,
                    "3日末收益%": end3,
                    "3日利润回吐%": giveback3,
                    "1日最大涨幅%": mfe1,
                    "1日最大回撤%": mae1
                })

        prev_trigger = trig

    return pd.DataFrame(events)


def run_breakout_confirmation_batch(master_df, tickers, start_date, end_date):
    parts = []
    prog = st.progress(0)
    msg = st.empty()
    for i, ticker in enumerate(tickers, 1):
        msg.write(f"测试突破后确认 {ticker} ({i}/{len(tickers)})")
        rr = master_df[master_df["Ticker"].astype(str).str.upper().eq(str(ticker).upper())]
        if not rr.empty:
            p = breakout_confirmation_test(rr.iloc[-1], start_date, end_date)
            if p is not None and not p.empty:
                parts.append(p)
        prog.progress(int(i/len(tickers)*100))
    msg.empty()
    prog.empty()
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def summarize_confirmation_test(df):
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for strategy, g in df.groupby("策略", sort=False):
        item = {"策略": strategy, "样本数": len(g)}
        for col, name in [
            ("1小时后%","1小时"),
            ("当日收盘%","当日"),
            ("下一交易日%","下一日"),
            ("3交易日%","3日")
        ]:
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            item[f"{name}胜率%"] = s.gt(0).mean()*100 if len(s) else np.nan
            item[f"{name}平均收益%"] = s.mean() if len(s) else np.nan
        for col in ["1日最大涨幅%","1日最大回撤%"]:
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            item[f"平均{col}"] = s.mean() if len(s) else np.nan
        rows.append(item)
    order = {"立即买":0, "等30分钟确认":1, "等60分钟确认":2}
    out = pd.DataFrame(rows)
    out["_o"] = out["策略"].map(order).fillna(9)
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def summarize_buy_type_quality(quality_out):
    """按回踩BUY / 突破BUY分别汇总样本数、胜率、平均收益和MFE/MAE。"""
    if quality_out is None or quality_out.empty:
        return pd.DataFrame()

    rows = []
    for buy_type, g in quality_out.groupby("BUY类型", dropna=False):
        item = {"BUY类型": buy_type, "样本数": len(g)}
        for col, label in [
            ("1小时后%", "1小时胜率%"),
            ("当日收盘%", "当日胜率%"),
            ("下一交易日收盘%", "下一日胜率%"),
            ("3交易日收盘%", "3日胜率%")
        ]:
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            item[label] = s.gt(0).mean()*100 if len(s) else np.nan
            item[label.replace("胜率","平均收益")] = s.mean() if len(s) else np.nan

        for col in ["1日最大涨幅%","1日最大回撤%","3日最大涨幅%","3日最大回撤%"]:
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            item[f"平均{col}"] = s.mean() if len(s) else np.nan
        rows.append(item)

    return pd.DataFrame(rows).sort_values("样本数", ascending=False).reset_index(drop=True)


st.markdown("### 🎯 BUY质量验证")
st.caption(
    "使用当前完全相同的B BUY逻辑，找出历史BUY首次触发点，并检查买入后1小时、当日收盘、"
    "下一交易日和3交易日表现，以及1日/3日最大涨幅与最大回撤。"
)

if st.button("🎯 验证当前B股票的BUY质量", use_container_width=True):
    if batch_start > batch_end:
        st.error("开始日期不能晚于结束日期。")
    elif not batch_tickers:
        st.warning("当前B没有可验证股票。")
    else:
        with st.spinner("正在验证历史BUY后的表现..."):
            quality_out = run_buy_quality_batch(master_df, batch_tickers, batch_start, batch_end)

        if quality_out.empty:
            st.warning("所选期间没有找到BUY信号，因此没有BUY质量结果。")
        else:
            nsignals = len(quality_out)
            nstocks = quality_out["股票代码"].nunique()

            def _positive_rate(col):
                s = pd.to_numeric(quality_out[col], errors="coerce").dropna()
                return (s.gt(0).mean()*100) if len(s) else np.nan

            r1h = _positive_rate("1小时后%")
            rclose = _positive_rate("当日收盘%")
            r1d = _positive_rate("下一交易日收盘%")
            r3d = _positive_rate("3交易日收盘%")

            st.success(
                f"BUY质量验证完成：{nstocks}只股票，共{nsignals}次BUY信号。"
            )
            q1,q2,q3,q4 = st.columns(4)
            q1.metric("1小时后为正", f"{r1h:.0f}%" if not pd.isna(r1h) else "NA")
            q2.metric("当日收盘为正", f"{rclose:.0f}%" if not pd.isna(rclose) else "NA")
            q3.metric("下一交易日为正", f"{r1d:.0f}%" if not pd.isna(r1d) else "NA")
            q4.metric("3交易日为正", f"{r3d:.0f}%" if not pd.isna(r3d) else "NA")

            qfmt = {
                "BUY价格":"{:.2f}", "15m量比":"{:.2f}","突破幅度%":"{:.2f}",
                "1小时后%":"{:.2f}", "当日收盘%":"{:.2f}",
                "下一交易日收盘%":"{:.2f}", "3交易日收盘%":"{:.2f}",
                "1日最大涨幅%":"{:.2f}", "1日最大回撤%":"{:.2f}",
                "3日最大涨幅%":"{:.2f}", "3日最大回撤%":"{:.2f}",
                "参考止损":"{:.2f}"
            }
            st.dataframe(
                quality_out.style.format(
                    {k:v for k,v in qfmt.items() if k in quality_out.columns},
                    na_rep=""
                ),
                hide_index=True,
                use_container_width=True
            )

            st.markdown("#### 📊 回踩 BUY vs 突破 BUY")
            type_summary = summarize_buy_type_quality(quality_out)
            if not type_summary.empty:
                type_fmt = {
                    c: "{:.1f}" for c in type_summary.columns
                    if c not in ["BUY类型","样本数"]
                }
                st.dataframe(
                    type_summary.style.format(type_fmt, na_rep=""),
                    hide_index=True,
                    use_container_width=True
                )

                st.caption(
                    "先看样本数，再比较胜率、平均收益、最大涨幅(MFE)和最大回撤(MAE)。"
                    "单一类型样本少于10次时，只作为方向性参考，不建议据此大幅调参。"
                )

            st.info(
                "判断原则：先看BUY后的方向是否多数为正，再看最大涨幅(MFE)与最大回撤(MAE)。"
                "目标先积累至少20–30次BUY信号；样本较少时不要据此大幅调参。"
            )

            qcsv = quality_out.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "💾 下载BUY质量结果",
                qcsv,
                file_name=f"B_BUY_Quality_{batch_start}_{batch_end}.csv",
                mime="text/csv",
                use_container_width=True
            )



st.markdown("### 🧪 突破后等待确认测试")
st.caption(
    "这一步只做历史比较，不改变LIVE买点。用V2.0原始突破条件找信号，"
    "比较：突破当刻立即买 vs 等30分钟确认 vs 等60分钟确认。"
)

if st.button("🧪 比较立即买 / 30分钟 / 60分钟", use_container_width=True):
    if batch_start > batch_end:
        st.error("开始日期不能晚于结束日期。")
    elif not batch_tickers:
        st.warning("当前B没有可测试股票。")
    else:
        with st.spinner("正在比较突破后的不同确认时间..."):
            confirm_out = run_breakout_confirmation_batch(
                master_df, batch_tickers, batch_start, batch_end
            )

        if confirm_out.empty:
            st.warning("所选期间没有可用于比较的原始突破信号。")
        else:
            confirm_summary = summarize_confirmation_test(confirm_out)
            st.success(
                f"测试完成：原始突破事件 "
                f"{confirm_out['原突破时间'].astype(str).groupby(confirm_out['股票代码']).count().sum()} 条策略记录。"
            )
            cfmt = {
                c:"{:.1f}" for c in confirm_summary.columns
                if c not in ["策略","样本数"]
            }
            st.dataframe(
                confirm_summary.style.format(cfmt, na_rep=""),
                hide_index=True,
                use_container_width=True
            )
            st.caption(
                "重点比较三行的样本数、当日/下一日胜率与平均收益、以及1日最大回撤。"
                "只有等待确认明显优于立即买时，才考虑把BREAKOUT WATCH加入LIVE。"
            )


            st.markdown("#### 💰 30分钟确认BUY：3日最高涨幅与利润回吐")
            c30 = confirm_out[confirm_out["策略"].eq("等30分钟确认")].copy()
            if not c30.empty:
                show_cols = [
                    "股票代码","原突破时间","确认买入时间","买入价格",
                    "第1日最高涨幅%","第1日收盘收益%",
                    "第2日最高涨幅%","第2日收盘收益%",
                    "第3日最高涨幅%","第3日收盘收益%",
                    "3日内最高浮盈%","3日末收益%","3日利润回吐%"
                ]
                show_cols = [c for c in show_cols if c in c30.columns]
                pfmt = {c:"{:.2f}" for c in show_cols if c not in ["股票代码","原突破时间","确认买入时间"]}
                st.dataframe(
                    c30[show_cols].style.format(pfmt, na_rep=""),
                    hide_index=True,
                    use_container_width=True
                )

                peak = pd.to_numeric(c30["3日内最高浮盈%"], errors="coerce")
                endv = pd.to_numeric(c30["3日末收益%"], errors="coerce")
                gb = pd.to_numeric(c30["3日利润回吐%"], errors="coerce")
                a,b,c = st.columns(3)
                a.metric("平均3日内最高浮盈", f"{peak.mean():.2f}%" if peak.notna().any() else "NA")
                b.metric("平均3日末收益", f"{endv.mean():.2f}%" if endv.notna().any() else "NA")
                c.metric("平均利润回吐", f"{gb.mean():.2f}%" if gb.notna().any() else "NA")

                st.caption(
                    "例如：3日内最高浮盈 +6%，3日末收益 +1%，则利润回吐=5个百分点。"
                    "如果最高浮盈明显高、但3日末收益很低，说明问题更可能在C的止盈/移动止损，而不是B的买点。"
                )

            with st.expander("查看每一次突破的详细结果"):
                st.dataframe(confirm_out, hide_index=True, use_container_width=True)

            ccsv = confirm_out.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "💾 下载突破确认测试结果",
                ccsv,
                file_name=f"B_Breakout_Confirmation_{batch_start}_{batch_end}.csv",
                mime="text/csv",
                use_container_width=True
            )


st.markdown("### 🔎 单只股票详细REPLAY")
replay_candidates = (
    master_df.loc[
        master_df["池状态"].astype(str).isin(["TRACKING","HOLDING","EXPIRED","CLOSED"]),
        "Ticker"
    ].astype(str).dropna().drop_duplicates().tolist()
    if master_df is not None and not master_df.empty and "Ticker" in master_df.columns
    else []
)

if replay_candidates:
    rc1, rc2, rc3 = st.columns([1.2,1,1])
    replay_ticker = rc1.selectbox("回放股票", replay_candidates, key="replay_ticker")
    replay_end = rc3.date_input(
        "结束日期",
        value=market_now().date(),
        max_value=market_now().date(),
        key="replay_end"
    )
    default_start = replay_end - pd.Timedelta(days=7)
    replay_start = rc2.date_input(
        "开始日期",
        value=default_start.date() if hasattr(default_start, "date") else default_start,
        max_value=replay_end,
        key="replay_start"
    )

    st.caption("建议一次测试 5–10 个交易日。Yahoo 15分钟历史数据可用范围有限，因此不要选择太久以前。")

    if st.button("▶️ 运行历史REPLAY", use_container_width=True):
        if replay_start > replay_end:
            st.error("开始日期不能晚于结束日期。")
        else:
            sel_rows = master_df[master_df["Ticker"].astype(str).str.upper().eq(str(replay_ticker).upper())]
            if sel_rows.empty:
                st.error("Master里找不到这只股票。")
            else:
                with st.spinner(f"正在回放 {replay_ticker} ..."):
                    replay_out, replay_err = replay_one_ticker(
                        sel_rows.iloc[-1],
                        replay_start,
                        replay_end
                    )

                if replay_err:
                    st.warning(replay_err)
                elif replay_out.empty:
                    st.info("所选期间没有可显示的状态变化。")
                else:
                    buy_count = int((replay_out["状态"] == "🟢 BUY").sum())
                    early_count = int((replay_out["状态"] == "🟠 EARLY BUY").sum())
                    avoid_count = int((replay_out["状态"] == "🔴 AVOID").sum())
                    st.success(
                        f"{replay_ticker} 回放完成：状态变化 {len(replay_out)} 次 ｜ "
                        f"BUY {buy_count} ｜ EARLY {early_count} ｜ AVOID {avoid_count}"
                    )

                    replay_fmt = {
                        "当前价格":"{:.2f}",
                        "15m RSI":"{:.1f}",
                        "15m量比":"{:.2f}","突破幅度%":"{:.2f}",
                        "参考入场":"{:.2f}",
                        "参考止损":"{:.2f}"
                    }
                    st.dataframe(
                        replay_out.style.format(
                            {k:v for k,v in replay_fmt.items() if k in replay_out.columns},
                            na_rep=""
                        ),
                        hide_index=True,
                        use_container_width=True
                    )

                    replay_csv = replay_out.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        "💾 下载REPLAY结果",
                        replay_csv,
                        file_name=f"B_Replay_{replay_ticker}_{replay_start}_{replay_end}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
else:
    st.info("Master中暂时没有股票可用于REPLAY。")


with st.expander("查看V4.3B V2.3规则"):
    st.markdown("""
**B不重新选股，也没有第二套100分。**

**LIVE自动监控：**
- 页面打开期间，美股交易时段约每15分钟自动刷新并重新检查。
- 每次15分钟检查一旦发现 WAIT → BUY / 新BUY，会立即在页面顶部提示。
- 约每2小时显示一次状态汇总。
- 每轮结果保存到 `B_Log`，用于识别上一轮状态。
- 手动“立即运行”按钮保留。

**REPLAY历史回放：**
- 不写入B_Log，不修改Master，不影响LIVE。
- 使用历史15m和60m数据逐时点调用同一套B decision逻辑。
- 只显示状态变化，例如 WAIT → EARLY BUY → BUY → WAIT。
- 用于快速测试BUY/EARLY BUY条件，不代表真实成交。
- V1.8新增：一键批量诊断当前B监控股票，并统计1H、VWAP、MACD、量比、突破、回踩各门槛通过次数和主要阻挡。
- V1.9新增：对历史BUY首次触发点计算1小时、当日、下一交易日、3交易日收益，以及1日/3日MFE和MAE，用于验证BUY质量。
- V2.0新增：支持最近10/20/30交易日长周期批量回放，并自动比较回踩BUY与突破BUY的胜率、平均收益、MFE和MAE。
- V2.1只优化突破BUY：量比门槛由1.20提高到1.50；15m MACD必须为正；15m RSI限定50–70；突破价不得高于前20根15m高点0.8%以上。回踩BUY参数完全不变。
- V2.2新增历史测试：用V2.0原始突破信号比较立即买、等待30分钟确认、等待60分钟确认；本版暂不改变LIVE等待逻辑。
- V2.3新增：对30分钟确认BUY显示第1/2/3日最高涨幅与收盘收益，并计算3日内最高浮盈、3日末收益和利润回吐，用于判断是否应优化C止盈。

**5交易日退出机制（V1.6）：** A表可以每天覆盖，只保留当天候选。B_MasterList独立累计每天A候选；未买入股票从最近一次A入选日起最多跟踪5个交易日，期间再次被A选中则重新从第1天计时；超过5日变为EXPIRED。真实持仓不受5日限制，直到SELL / STOP / TAKE PROFIT。

- 1H：EMA20/EMA50、MACD、RSI确认大方向。
- 15min：VWAP、EMA9/EMA20、MACD、RSI、成交量、突破和回踩。
- 突破BUY：1H强 + 15min突破 + 量比≥1.20 + VWAP上方。
- 回踩BUY：1H趋势保持 + 15min回踩VWAP/EMA后企稳。
- WAIT：VWAP下方、接近突破但未确认、基本面弱、或明显追高。
- AVOID：1H趋势/动量已经破坏。
""")
