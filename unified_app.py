
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
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
# CMS UNIFIED APP V1
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
.block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1550px;}
[data-testid="stMetric"] {
    background: rgba(120,120,120,0.08);
    border: 1px solid rgba(130,130,130,0.18);
    padding: 14px 16px;
    border-radius: 14px;
}
.cms-card {
    border: 1px solid rgba(130,130,130,0.18);
    border-radius: 16px;
    padding: 16px 18px;
    background: rgba(120,120,120,0.05);
    margin-bottom: 10px;
}
.cms-buy {font-size: 1.05rem; font-weight: 700;}
.cms-small {opacity: 0.75; font-size: 0.90rem;}
.cms-title {font-weight: 800; font-size: 2.0rem; margin-bottom: -2px;}
.cms-subtitle {opacity: .70; margin-bottom: 12px;}
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

@st.cache_data(ttl=60, show_spinner=False)
def load_sheet(sheet_name):
    book = get_book()
    ws = book.worksheet(sheet_name)
    rows = ws.get_all_records()
    return normalize(pd.DataFrame(rows))

@st.cache_data(ttl=120, show_spinner=False)
def load_price_history(ticker, period="3mo", interval="1d"):
    if not ticker:
        return pd.DataFrame()
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
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
    return {
        "BUY": int(vals.str.contains("BUY", case=False, na=False) &
                   ~vals.str.contains("EARLY", case=False, na=False)).sum(),
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



# ---------- sidebar ----------
with st.sidebar:
    st.markdown("## 📈 CMS")
    st.caption("Unified App V1 · 一个网址看完整 A + B + C")
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
    refresh_seconds = st.selectbox("刷新频率", [60, 120, 300, 900], index=1)

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
master_active = active_master(master_df)
pos_df = holdings(master_df)
counts = decision_counts(master_active)
now = market_now()


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

st.caption(
    "Unified App V1：一个网址统一查看 A、B、C。"
    "当前版本是安全的只读整合层，不改变已经冻结的交易引擎。"
)

# ============================================================
# HOME
# ============================================================
if page == "🏠 首页":
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("今日 A 正式候选", len(a_buy))
    m2.metric("B BUY", counts.get("BUY", 0))
    m3.metric("B EARLY", counts.get("EARLY", 0))
    m4.metric("真实持仓", len(pos_df))
    m5.metric("今日检查/提醒", alert_today_count(log_df))

    st.divider()
    lcol, rcol = st.columns([1.05, 1.55], gap="large")

    with lcol:
        st.subheader("🔥 Today's Opportunities")
        opp = compact_opportunity_table(master_active)
        if opp.empty:
            st.info("目前没有活跃的 B 候选。")
        else:
            for _, row in opp.head(6).iterrows():
                tk = str(row.get("Ticker", ""))
                company = str(row.get("Company", ""))
                dec = status_badge(row.get("最后决策", ""))
                px = money_text(row.get("最后价格", np.nan))
                room = str(row.get("空间等级", "—"))
                reason = str(row.get("最后决策依据", ""))
                st.markdown(
                    f"""
                    <div class="cms-card">
                      <div class="cms-buy">{dec} &nbsp; {tk} &nbsp; <span class="cms-small">{company}</span></div>
                      <div>{px} &nbsp;&nbsp; | &nbsp;&nbsp; {room}</div>
                      <div class="cms-small">{reason[:150]}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

        st.subheader("💼 Positions")
        psmall = compact_position_table(pos_df)
        if psmall.empty:
            st.caption("目前没有标记为真实持仓的股票。")
        else:
            showcols = [c for c in ["Ticker","C阶段","最后价格","最高浮盈%","动态保护价"] if c in psmall.columns]
            st.dataframe(psmall[showcols], hide_index=True, use_container_width=True)

    with rcol:
        tickers = union_tickers(master_active, a_buy)
        selected_home = st.selectbox(
            "快速查看股票",
            tickers if tickers else [""],
            index=0,
            key="home_ticker"
        )
        if selected_home:
            h = load_price_history(selected_home, "3mo", "1d")
            if not h.empty and "Close" in h.columns:
                st.subheader(f"{selected_home} · 3个月日线")
                st.line_chart(h[["Close"]], height=350)
            else:
                st.warning("暂时无法取得价格图。")

            row = ticker_row(selected_home, master_df, a_df)
            x1, x2, x3, x4 = st.columns(4)
            x1.metric("当前/最后价", money_text(row.get("最后价格", row.get("价格", np.nan))))
            x2.metric("参考止损", money_text(row.get("参考止损", row.get("持仓止损", np.nan))))
            x3.metric("TP1", money_text(row.get("TP1", np.nan)))
            x4.metric("TP2", money_text(row.get("TP2", np.nan)))

            st.markdown("#### 🧠 CMS Decision")
            st.write(status_badge(row.get("最后决策", "—")))
            reason = row.get("最后决策依据", "")
            if str(reason).strip():
                st.caption(str(reason))

            z1, z2, z3, z4 = st.columns(4)
            z1.metric("1H", str(row.get("1H状态", "—")))
            rv = sfloat(row.get("15m RSI", np.nan))
            vv = sfloat(row.get("15m量比", np.nan))
            z2.metric("15m RSI", f"{rv:.1f}" if not pd.isna(rv) else "—")
            z3.metric("15m量比", f"{vv:.2f}" if not pd.isna(vv) else "—")
            z4.metric("空间", str(row.get("空间等级", "—")))


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

    tickers = union_tickers(master_df, a_df)
    if not tickers:
        st.info("目前没有股票可查看。")
    else:
        d1, d2 = st.columns([1, 3])
        with d1:
            tk = st.selectbox("股票", tickers, key="detail_ticker")
            period = st.selectbox("图表区间", ["1mo","3mo","6mo","1y"], index=1)
        with d2:
            row = ticker_row(tk, master_df, a_df)
            title_company = str(row.get("Company", ""))
            st.markdown(f"### {tk} {title_company}")

        hist = load_price_history(tk, period, "1d")
        if not hist.empty and "Close" in hist.columns:
            st.line_chart(hist[["Close"]], height=430)
        else:
            st.warning("价格数据暂时不可用。")

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
    "CMS Unified App V1 · 这是第一步：把 A / B / C 做成一个软件入口。"
    "策略核心保持冻结。后续再把“运行 A、真实 B 后台监控、持仓操作、收益统计”逐步搬进同一个 App。"
)
