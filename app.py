import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone

st.set_page_config(
    page_title="CMS-100 Stock Screener",
    page_icon="📈",
    layout="wide"
)

st.title("📈 CMS-100 自动选股系统")

st.caption(
    "Catalyst + Momentum + Setup | 自动筛选 BUY / WATCH / PASS"
)


# =========================================================
# 基础设置
# =========================================================

SECTOR_ETF = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Financial": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

POSITIVE_KEYWORDS = [
    "beat",
    "beats",
    "surge",
    "growth",
    "raises guidance",
    "raised guidance",
    "upgrade",
    "approval",
    "approved",
    "partnership",
    "contract",
    "order",
    "record revenue",
    "strong demand",
    "launch",
    "expands",
    "acquisition",
    "profit",
]


# =========================================================
# 分数函数
# =========================================================

def score_volume(rvol):
    if pd.isna(rvol):
        return 0
    if rvol >= 2.0:
        return 15
    elif rvol >= 1.5:
        return 12
    elif rvol >= 1.2:
        return 8
    elif rvol >= 0.8:
        return 4
    return 0


def score_rr(rr):
    if pd.isna(rr) or rr <= 0:
        return 0
    if rr >= 3.0:
        return 15
    elif rr >= 2.5:
        return 13
    elif rr >= 2.0:
        return 10
    elif rr >= 1.5:
        return 6
    return 0


# =========================================================
# 下载股票数据
# =========================================================

@st.cache_data(ttl=1800)
def download_stock(ticker, period="1y"):

    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False
    )

    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df.dropna(how="all")


# =========================================================
# 20日收益
# =========================================================

def last_return(ticker, days=20):

    try:

        df = download_stock(
            ticker,
            period="3mo"
        )

        if df is None or len(df) <= days:
            return np.nan

        close = df["Close"].dropna()

        return float(
            close.iloc[-1] /
            close.iloc[-days - 1]
            - 1
        )

    except Exception:
        return np.nan


# =========================================================
# 新闻 Catalyst 分数
# =========================================================

@st.cache_data(ttl=1800)
def get_news_score(ticker):

    try:
        tk = yf.Ticker(ticker)
        news = tk.news or []
    except Exception:
        return 0, []

    recent_titles = []

    now = datetime.now(
        timezone.utc
    ).timestamp()

    fourteen_days = 14 * 86400

    for item in news:

        title = ""
        ts = None

        if isinstance(item, dict):

            title = item.get(
                "title",
                ""
            ) or ""

            ts = item.get(
                "providerPublishTime"
            )

            if (
                not title
                and isinstance(
                    item.get("content"),
                    dict
                )
            ):

                content = item["content"]

                title = content.get(
                    "title",
                    ""
                ) or ""

                pub = content.get(
                    "pubDate"
                )

                if pub:
                    try:
                        ts = pd.Timestamp(
                            pub
                        ).timestamp()
                    except Exception:
                        ts = None

        if not title:
            continue

        if (
            ts is None
            or now - ts <= fourteen_days
        ):
            recent_titles.append(title)

    n = len(recent_titles)

    if n >= 8:
        base = 14
    elif n >= 5:
        base = 10
    elif n >= 2:
        base = 6
    elif n >= 1:
        base = 3
    else:
        base = 0

    text = " ".join(
        recent_titles
    ).lower()

    hits = sum(
        1
        for kw in POSITIVE_KEYWORDS
        if kw in text
    )

    bonus = min(
        6,
        hits * 2
    )

    score = min(
        20,
        base + bonus
    )

    return score, recent_titles[:8]


# =========================================================
# 公司信息
# =========================================================

@st.cache_data(ttl=3600)
def get_company_info(ticker):

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}

        company = (
            info.get("shortName")
            or info.get("longName")
            or ticker
        )

        sector = info.get(
            "sector",
            "Unknown"
        )

        market_cap = info.get(
            "marketCap",
            np.nan
        )

        return company, sector, market_cap

    except Exception:
        return ticker, "Unknown", np.nan


# =========================================================
# 快速初筛
# =========================================================

def quick_screen(ticker):

    try:

        df = download_stock(
            ticker,
            period="1y"
        )

        if df is None or len(df) < 200:
            return None

        close = df["Close"].astype(float)
        volume = df["Volume"].astype(float)

        price = float(close.iloc[-1])

        ma20 = float(
            close.rolling(20).mean().iloc[-1]
        )

        ma50 = float(
            close.rolling(50).mean().iloc[-1]
        )

        ma200 = float(
            close.rolling(200).mean().iloc[-1]
        )

        avg_vol20 = float(
            volume.rolling(20).mean().iloc[-1]
        )

        today_vol = float(
            volume.iloc[-1]
        )

        rvol = (
            today_vol / avg_vol20
            if avg_vol20 > 0
            else np.nan
        )

        ret20 = float(
            close.iloc[-1] /
            close.iloc[-21]
            - 1
        )

        dollar_volume = (
            price * avg_vol20
        )

        # --------------------------
        # 第一层过滤条件
        # --------------------------

        if price < 5:
            return None

        if price <= ma20:
            return None

        if price <= ma50:
            return None

        if price <= ma200:
            return None

        if ma20 <= ma50:
            return None

        if rvol < 0.8:
            return None

        # 平均日交易金额至少 2,000 万美元
        if dollar_volume < 20_000_000:
            return None

        return {
            "Ticker": ticker,
            "Price": price,
            "MA20": ma20,
            "MA50": ma50,
            "MA200": ma200,
            "RVOL": rvol,
            "20D Return": ret20,
            "Dollar Volume": dollar_volume
        }

    except Exception:
        return None


# =========================================================
# 完整 CMS-100 分析
# =========================================================

def analyze_stock(ticker):

    ticker = ticker.upper().strip()

    df = download_stock(
        ticker,
        period="1y"
    )

    if df is None or len(df) < 55:
        raise ValueError(
            "历史数据不足。"
        )

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    price = float(close.iloc[-1])

    ma20 = float(
        close.rolling(20).mean().iloc[-1]
    )

    ma50 = float(
        close.rolling(50).mean().iloc[-1]
    )

    if len(close) >= 200:
        ma200 = float(
            close.rolling(200).mean().iloc[-1]
        )
    else:
        ma200 = np.nan

    avg_vol20 = float(
        volume.rolling(20).mean().iloc[-1]
    )

    today_vol = float(
        volume.iloc[-1]
    )

    rvol = (
        today_vol / avg_vol20
        if avg_vol20 > 0
        else np.nan
    )

    resistance = float(
        high
        .shift(1)
        .rolling(20)
        .max()
        .iloc[-1]
    )

    recent_low20 = float(
        low
        .shift(1)
        .rolling(20)
        .min()
        .iloc[-1]
    )

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    atr14 = float(
        true_range
        .rolling(14)
        .mean()
        .iloc[-1]
    )

    # =====================================================
    # Trend
    # =====================================================

    trend_score = 0

    if price > ma20:
        trend_score += 5

    if price > ma50:
        trend_score += 5

    if ma20 > ma50:
        trend_score += 5

    if (
        not pd.isna(ma200)
        and price > ma200
    ):
        trend_score += 5


    # =====================================================
    # Breakout
    # =====================================================

    if (
        price > resistance
        and rvol >= 1.5
    ):
        breakout_score = 15

    elif price > resistance:
        breakout_score = 12

    elif price >= resistance * 0.98:
        breakout_score = 8

    elif price >= resistance * 0.95:
        breakout_score = 4

    else:
        breakout_score = 0


    # =====================================================
    # Volume
    # =====================================================

    volume_score = score_volume(
        rvol
    )


    # =====================================================
    # Stop
    # =====================================================

    stop = min(
        ma20,
        price - 1.5 * atr14
    )

    if stop >= price:
        stop = (
            price - 1.5 * atr14
        )

    risk = price - stop


    # =====================================================
    # TP1 / TP2
    # =====================================================

    recent_range = max(
        resistance - recent_low20,
        2.0 * atr14
    )

    tp1 = (
        price + recent_range
    )

    tp2 = (
        price
        + 1.5 * recent_range
    )

    if risk > 0:
        rr = (
            tp1 - price
        ) / risk
    else:
        rr = np.nan

    rr_score = score_rr(
        rr
    )


    # =====================================================
    # Sector
    # =====================================================

    company, sector, market_cap = (
        get_company_info(
            ticker
        )
    )

    sector_etf = SECTOR_ETF.get(
        sector
    )

    if sector_etf:

        sec_ret = last_return(
            sector_etf,
            20
        )

        spy_ret = last_return(
            "SPY",
            20
        )

        if (
            pd.isna(sec_ret)
            or pd.isna(spy_ret)
        ):
            relative_return = np.nan
        else:
            relative_return = (
                sec_ret - spy_ret
            )

        if pd.isna(relative_return):
            sector_score = 7

        elif relative_return >= 0.05:
            sector_score = 15

        elif relative_return >= 0.02:
            sector_score = 12

        elif relative_return >= 0:
            sector_score = 8

        elif relative_return >= -0.03:
            sector_score = 4

        else:
            sector_score = 0

    else:

        relative_return = np.nan
        sector_score = 7


    # =====================================================
    # Catalyst
    # =====================================================

    catalyst_score, headlines = (
        get_news_score(
            ticker
        )
    )


    # =====================================================
    # CMS 总分
    # =====================================================

    total_score = int(
        round(
            sector_score
            + catalyst_score
            + trend_score
            + breakout_score
            + volume_score
            + rr_score
        )
    )


    # =====================================================
    # Grade
    # =====================================================

    if total_score >= 85:
        grade = "A"

    elif total_score >= 75:
        grade = "B"

    elif total_score >= 65:
        grade = "C"

    else:
        grade = "PASS"


    # =====================================================
    # Signal
    # =====================================================

    if (
        total_score >= 85
        and trend_score >= 15
        and rr_score >= 10
        and breakout_score >= 12
        and rvol >= 1.2
    ):
        signal = "BUY"

    elif (
        total_score >= 75
        and trend_score >= 15
    ):
        signal = "WATCH"

    else:
        signal = "PASS"


    return {
        "Ticker": ticker,
        "Company": company,
        "Sector": sector,
        "Market Cap": market_cap,
        "Price": price,
        "MA20": ma20,
        "MA50": ma50,
        "MA200": ma200,
        "RVOL": rvol,
        "Resistance": resistance,
        "ATR14": atr14,
        "Stop": stop,
        "TP1": tp1,
        "TP2": tp2,
        "R/R": rr,
        "Sector Score": sector_score,
        "Catalyst Score": catalyst_score,
        "Trend Score": trend_score,
        "Breakout Score": breakout_score,
        "Volume Score": volume_score,
        "R/R Score": rr_score,
        "CMS": total_score,
        "Grade": grade,
        "Signal": signal,
        "Headlines": headlines
    }


# =========================================================
# S&P 500 股票名单
# =========================================================

@st.cache_data(ttl=86400)
def get_sp500_tickers():

    url = (
        "https://en.wikipedia.org/wiki/"
        "List_of_S%26P_500_companies"
    )

    tables = pd.read_html(url)

    df = tables[0]

    tickers = (
        df["Symbol"]
        .str.replace(
            ".",
            "-",
            regex=False
        )
        .tolist()
    )

    return tickers


# =========================================================
# Single Stock 页面
# =========================================================

tab1, tab2 = st.tabs(
    [
        "🔎 Single Stock",
        "🚀 Market Scanner"
    ]
)


with tab1:

    st.subheader(
        "单只股票分析"
    )

    ticker = st.text_input(
        "输入股票代码",
        value="TEM",
        placeholder="例如 TEM / PATH / PLUG / WDC / NVDA"
    )

    if st.button(
        "开始分析",
        key="single_analyze"
    ):

        try:

            r = analyze_stock(
                ticker
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "CMS Score",
                f"{r['CMS']}/100"
            )

            c2.metric(
                "Grade",
                r["Grade"]
            )

            c3.metric(
                "Signal",
                r["Signal"]
            )

            c4.metric(
                "RVOL",
                f"{r['RVOL']:.2f}x"
            )


            if r["Signal"] == "BUY":

                st.success(
                    "🟢 BUY：当前条件满足 CMS 买入规则。"
                )

            elif r["Signal"] == "WATCH":

                st.warning(
                    "🟡 WATCH：值得关注，但买入条件还没有全部确认。"
                )

            else:

                st.error(
                    "🔴 PASS：当前条件不足。"
                )


            st.subheader(
                f"{r['Company']} ({r['Ticker']})"
            )

            st.write(
                f"Sector: {r['Sector']}"
            )


            score_df = pd.DataFrame(
                {
                    "Module": [
                        "Sector",
                        "Catalyst",
                        "Trend",
                        "Breakout",
                        "Volume",
                        "Risk / Reward"
                    ],
                    "Score": [
                        r["Sector Score"],
                        r["Catalyst Score"],
                        r["Trend Score"],
                        r["Breakout Score"],
                        r["Volume Score"],
                        r["R/R Score"]
                    ],
                    "Max": [
                        15,
                        20,
                        20,
                        15,
                        15,
                        15
                    ]
                }
            )

            st.dataframe(
                score_df,
                use_container_width=True,
                hide_index=True
            )


            price_df = pd.DataFrame(
                [
                    {
                        "Price": r["Price"],
                        "MA20": r["MA20"],
                        "MA50": r["MA50"],
                        "MA200": r["MA200"],
                        "Resistance": r["Resistance"],
                        "Stop": r["Stop"],
                        "TP1": r["TP1"],
                        "TP2": r["TP2"],
                        "R/R": r["R/R"]
                    }
                ]
            )

            st.subheader(
                "关键价位"
            )

            st.dataframe(
                price_df.style.format(
                    "{:.2f}"
                ),
                use_container_width=True,
                hide_index=True
            )


            st.subheader(
                "近期 Catalyst 新闻"
            )

            if r["Headlines"]:

                for h in r["Headlines"]:
                    st.write("•", h)

            else:

                st.write(
                    "没有抓到近期新闻。"
                )


        except Exception as e:

            st.error(
                f"分析失败：{e}"
            )


# =========================================================
# Market Scanner 页面
# =========================================================

with tab2:

    st.subheader(
        "S&P 500 Market Scanner"
    )

    st.write(
        """
程序会先快速筛选趋势和成交量，
然后对最强候选股运行完整 CMS-100 分析。
"""
    )

    candidate_limit = st.slider(
        "快速初筛后最多分析多少只股票",
        min_value=10,
        max_value=50,
        value=20,
        step=5
    )

    top_n = st.slider(
        "显示 Top N",
        min_value=5,
        max_value=20,
        value=10,
        step=1
    )


    if st.button(
        "🚀 Scan S&P 500",
        key="market_scan"
    ):

        try:

            tickers = get_sp500_tickers()

            quick_results = []

            progress = st.progress(0)

            status = st.empty()

            total = len(tickers)


            # =================================================
            # 第一阶段：快速扫描
            # =================================================

            for i, ticker in enumerate(
                tickers
            ):

                status.write(
                    f"快速扫描 {ticker} "
                    f"({i+1}/{total})"
                )

                result = quick_screen(
                    ticker
                )

                if result is not None:

                    quick_results.append(
                        result
                    )

                progress.progress(
                    (i + 1) / total
                )


            if not quick_results:

                st.warning(
                    "没有股票通过快速筛选。"
                )

                st.stop()


            quick_df = pd.DataFrame(
                quick_results
            )


            # =================================================
            # 按 20D return + RVOL 排序
            # =================================================

            quick_df["Quick Rank Score"] = (

                quick_df[
                    "20D Return"
                ].rank(
                    pct=True
                )

                +

                quick_df[
                    "RVOL"
                ].rank(
                    pct=True
                )

            )


            quick_df = (
                quick_df
                .sort_values(
                    "Quick Rank Score",
                    ascending=False
                )
                .head(
                    candidate_limit
                )
            )


            st.info(
                f"快速筛选完成："
                f"{len(quick_results)} 只通过基础条件，"
                f"现在对前 {len(quick_df)} 只计算完整 CMS。"
            )


            # =================================================
            # 第二阶段：完整 CMS
            # =================================================

            cms_results = []

            progress2 = st.progress(0)

            total2 = len(
                quick_df
            )


            for i, ticker in enumerate(
                quick_df["Ticker"]
            ):

                status.write(
                    f"CMS 分析 {ticker} "
                    f"({i+1}/{total2})"
                )

                try:

                    r = analyze_stock(
                        ticker
                    )

                    cms_results.append(
                        r
                    )

                except Exception:

                    pass


                progress2.progress(
                    (i + 1) / total2
                )


            status.empty()


            if not cms_results:

                st.warning(
                    "完整 CMS 分析没有得到结果。"
                )

                st.stop()


            result_df = pd.DataFrame(
                cms_results
            )


            result_df = (
                result_df
                .sort_values(
                    [
                        "CMS",
                        "Trend Score",
                        "RVOL"
                    ],
                    ascending=[
                        False,
                        False,
                        False
                    ]
                )
            )


            # =================================================
            # 输出 Top N
            # =================================================

            display_cols = [

                "Ticker",

                "Company",

                "Sector",

                "CMS",

                "Grade",

                "Signal",

                "Price",

                "RVOL",

                "Trend Score",

                "Breakout Score",

                "Volume Score",

                "Catalyst Score",

                "R/R",

                "Stop",

                "TP1",

                "TP2"

            ]


            top_df = (
                result_df[
                    display_cols
                ]
                .head(
                    top_n
                )
                .copy()
            )


            st.subheader(
                f"🏆 Top {top_n} CMS Candidates"
            )


            st.dataframe(

                top_df.style.format(
                    {
                        "Price": "{:.2f}",
                        "RVOL": "{:.2f}",
                        "R/R": "{:.2f}",
                        "Stop": "{:.2f}",
                        "TP1": "{:.2f}",
                        "TP2": "{:.2f}"
                    }
                ),

                use_container_width=True,

                hide_index=True

            )


            # =================================================
            # BUY only
            # =================================================

            buy_df = result_df[
                result_df["Signal"]
                == "BUY"
            ]


            st.subheader(
                "🟢 BUY Candidates"
            )


            if buy_df.empty:

                st.write(
                    "今天没有股票满足严格 BUY 条件。"
                )

            else:

                st.dataframe(

                    buy_df[
                        display_cols
                    ].style.format(
                        {
                            "Price": "{:.2f}",
                            "RVOL": "{:.2f}",
                            "R/R": "{:.2f}",
                            "Stop": "{:.2f}",
                            "TP1": "{:.2f}",
                            "TP2": "{:.2f}"
                        }
                    ),

                    use_container_width=True,

                    hide_index=True

                )


        except Exception as e:

            st.error(
                f"扫描失败：{e}"
            )


# =========================================================
# 说明
# =========================================================

st.divider()

st.caption(
    """
CMS-100 用于股票筛选和交易纪律管理，不构成投资建议。
Market Scanner 当前扫描 S&P 500。
Yahoo Finance 数据可能存在延迟或临时限流。
"""
)
