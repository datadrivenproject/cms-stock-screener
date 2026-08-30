import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone

st.set_page_config(
    page_title="CMS-100 自动选股",
    page_icon="📈",
    layout="wide"
)

# =========================
# 1. 基本设置
# =========================

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

# =========================
# 2. 成交量评分
# =========================

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

    else:
        return 0


# =========================
# 3. Risk / Reward评分
# =========================

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

    else:
        return 0


# =========================
# 4. 下载股票数据
# =========================

def download_single(ticker, period="1y"):

    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False
    )

    if df is None or df.empty:
        raise ValueError(
            f"没有获取到 {ticker} 的价格数据。请检查股票代码。"
        )

    # 处理 yfinance MultiIndex
    if isinstance(df.columns, pd.MultiIndex):

        if ticker in df.columns.get_level_values(-1):

            df = df.xs(
                ticker,
                axis=1,
                level=-1
            )

        else:

            df.columns = df.columns.get_level_values(0)

    return df.dropna(how="all")


# =========================
# 5. 计算20日收益
# =========================

def last_return(ticker, days=20):

    try:

        d = download_single(
            ticker,
            period="3mo"
        )

        c = d["Close"].dropna()

        if len(c) <= days:
            return np.nan

        return float(
            c.iloc[-1] /
            c.iloc[-days - 1]
            - 1
        )

    except:
        return np.nan


# =========================
# 6. 新闻 Catalyst评分
# =========================

def get_recent_news_score(tk):

    try:
        news = tk.news or []

    except:
        news = []

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

            # yfinance 新格式
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

                    except:
                        ts = None

        if not title:
            continue

        if (
            ts is None
            or (now - ts) <= fourteen_days
        ):

            recent_titles.append(
                title
            )

    n = len(recent_titles)

    # 新闻活跃度基础分
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

    # 正面关键词
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


# =========================
# 7. 主分析函数
# =========================

def analyze(ticker):

    ticker = ticker.upper().strip()

    tk = yf.Ticker(
        ticker
    )

    df = download_single(
        ticker,
        period="1y"
    )

    if len(df) < 55:

        raise ValueError(
            "历史数据不足55个交易日，无法稳定计算。"
        )

    close = df["Close"].astype(float)

    high = df["High"].astype(float)

    low = df["Low"].astype(float)

    volume = df["Volume"].astype(float)


    # ======================
    # 当前价格
    # ======================

    price = float(
        close.iloc[-1]
    )


    # ======================
    # 均线
    # ======================

    ma20 = float(
        close
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    ma50 = float(
        close
        .rolling(50)
        .mean()
        .iloc[-1]
    )

    if len(close) >= 200:

        ma200 = float(
            close
            .rolling(200)
            .mean()
            .iloc[-1]
        )

    else:
        ma200 = np.nan


    # ======================
    # 成交量
    # ======================

    avg_volume20 = float(
        volume
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    today_volume = float(
        volume.iloc[-1]
    )

    if avg_volume20 > 0:

        rvol = (
            today_volume /
            avg_volume20
        )

    else:
        rvol = np.nan


    # ======================
    # Resistance
    # 过去20日最高点
    # 不包括今天
    # ======================

    resistance = float(

        high
        .shift(1)
        .rolling(20)
        .max()
        .iloc[-1]

    )


    # ======================
    # 最近20日低点
    # ======================

    recent_low20 = float(

        low
        .shift(1)
        .rolling(20)
        .min()
        .iloc[-1]

    )


    # ======================
    # ATR14
    # ======================

    previous_close = close.shift(1)

    true_range = pd.concat(

        [

            high - low,

            (
                high
                - previous_close
            ).abs(),

            (
                low
                - previous_close
            ).abs()

        ],

        axis=1

    ).max(axis=1)

    atr14 = float(

        true_range
        .rolling(14)
        .mean()
        .iloc[-1]

    )


    # ======================
    # Trend Score
    # 满分20
    # ======================

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


    # ======================
    # Breakout Score
    # 满分15
    # ======================

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


    # ======================
    # Volume Score
    # ======================

    volume_score = score_volume(
        rvol
    )


    # ======================
    # Stop Loss
    # ======================

    stop = min(

        ma20,

        price - 1.5 * atr14

    )

    if stop >= price:

        stop = (
            price
            - 1.5 * atr14
        )


    risk = price - stop


    # ======================
    # TP1 / TP2
    # ======================

    recent_range = max(

        resistance - recent_low20,

        2.0 * atr14

    )

    tp1 = (
        price
        + recent_range
    )

    tp2 = (
        price
        + 1.5 * recent_range
    )


    # ======================
    # Risk / Reward
    # ======================

    if risk > 0:

        rr = (
            tp1 - price
        ) / risk

    else:
        rr = np.nan


    rr_score = score_rr(
        rr
    )


    # ======================
    # 公司行业
    # ======================

    try:

        info = tk.info or {}

        sector = info.get(
            "sector",
            "Unknown"
        )

        company = (
            info.get("shortName")
            or
            info.get("longName")
            or
            ticker
        )

    except:

        sector = "Unknown"

        company = ticker


    # ======================
    # Sector Score
    # ======================

    sector_etf = SECTOR_ETF.get(
        sector
    )

    if sector_etf:

        sector_return = last_return(
            sector_etf,
            20
        )

        spy_return = last_return(
            "SPY",
            20
        )

        if (
            pd.isna(sector_return)
            or
            pd.isna(spy_return)
        ):

            relative_return = np.nan

        else:

            relative_return = (
                sector_return
                - spy_return
            )


        if pd.isna(
            relative_return
        ):

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


    # ======================
    # Catalyst Score
    # ======================

    catalyst_score, headlines = (
        get_recent_news_score(
            tk
        )
    )


    # ======================
    # CMS总分
    # ======================

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


    # ======================
    # BUY / WATCH / PASS
    # ======================

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


    # ======================
    # Grade
    # ======================

    if total_score >= 85:

        grade = "A"

    elif total_score >= 75:

        grade = "B"

    elif total_score >= 65:

        grade = "C"

    else:

        grade = "PASS"


    return {

        "Ticker": ticker,

        "Company": company,

        "Sector": sector,

        "Price": price,

        "MA20": ma20,

        "MA50": ma50,

        "MA200": ma200,

        "Today Volume": today_volume,

        "20D Avg Volume": avg_volume20,

        "RVOL": rvol,

        "Resistance": resistance,

        "ATR14": atr14,

        "Stop": stop,

        "TP1": tp1,

        "TP2": tp2,

        "Sector Score": sector_score,

        "Catalyst Score": catalyst_score,

        "Trend Score": trend_score,

        "Breakout Score": breakout_score,

        "Volume Score": volume_score,

        "R/R Score": rr_score,

        "R/R": rr,

        "CMS": total_score,

        "Grade": grade,

        "Signal": signal,

        "Headlines": headlines

    }


# =========================
# 8. 网页界面
# =========================

st.title("📈 CMS-100 自动选股系统")

st.write(
    """
输入一个股票代码，程序会自动分析：

- Trend
- Breakout
- Volume
- Catalyst
- Sector Strength
- Risk / Reward

然后自动给出：

### BUY / WATCH / PASS
"""
)


ticker = st.text_input(
    "输入股票代码",
    value="TEM",
    placeholder="例如 TEM / PATH / PLUG / WDC / AAPL"
)


if st.button(
    "开始分析",
    type="primary"
):

    try:

        result = analyze(
            ticker
        )


        # ==================
        # 最重要结果
        # ==================

        col1, col2, col3, col4 = st.columns(4)


        col1.metric(

            "CMS Score",

            f"{result['CMS']}/100"

        )


        col2.metric(

            "Grade",

            result["Grade"]

        )


        col3.metric(

            "Signal",

            result["Signal"]

        )


        col4.metric(

            "RVOL",

            f"{result['RVOL']:.2f}x"

        )


        # ==================
        # BUY / WATCH / PASS
        # ==================

        if result["Signal"] == "BUY":

            st.success(
                "🟢 BUY：当前评分和技术条件同时满足。"
            )


        elif result["Signal"] == "WATCH":

            st.warning(
                "🟡 WATCH：股票值得关注，但还没有满足全部买入条件。"
            )


        else:

            st.error(
                "🔴 PASS：当前条件不足，暂时不买。"
            )


        # ==================
        # 公司信息
        # ==================

        st.subheader(

            f"{result['Company']} ({result['Ticker']})"

        )

        st.write(

            "行业：",

            result["Sector"]

        )


        # ==================
        # 六项评分
        # ==================

        st.subheader(
            "CMS-100 评分"
        )


        scoring_table = pd.DataFrame({

            "项目": [

                "Sector",

                "Catalyst",

                "Trend",

                "Breakout",

                "Volume",

                "Risk / Reward"

            ],

            "Score": [

                result[
                    "Sector Score"
                ],

                result[
                    "Catalyst Score"
                ],

                result[
                    "Trend Score"
                ],

                result[
                    "Breakout Score"
                ],

                result[
                    "Volume Score"
                ],

                result[
                    "R/R Score"
                ]

            ],

            "Maximum": [

                15,

                20,

                20,

                15,

                15,

                15

            ]

        })


        st.dataframe(

            scoring_table,

            use_container_width=True,

            hide_index=True

        )


        # ==================
        # 股票价格
        # ==================

        st.subheader(
            "关键价位"
        )


        price_table = pd.DataFrame(

            [

                {

                    "Current Price":
                        result["Price"],

                    "MA20":
                        result["MA20"],

                    "MA50":
                        result["MA50"],

                    "MA200":
                        result["MA200"],

                    "Resistance":
                        result["Resistance"],

                    "ATR14":
                        result["ATR14"],

                    "Stop":
                        result["Stop"],

                    "TP1":
                        result["TP1"],

                    "TP2":
                        result["TP2"],

                    "Risk/Reward":
                        result["R/R"]

                }

            ]

        )


        st.dataframe(

            price_table.style.format(
                "{:.2f}"
            ),

            use_container_width=True,

            hide_index=True

        )


        # ==================
        # 买入规则
        # ==================

        st.subheader(
            "BUY硬条件"
        )


        st.write(
            """
只有同时满足下面条件才会显示 **BUY**：

- CMS Score ≥ 85
- Trend Score ≥ 15
- Risk/Reward Score ≥ 10
- Breakout Score ≥ 12
- RVOL ≥ 1.2x
"""
        )


        # ==================
        # 新闻
        # ==================

        st.subheader(
            "近期新闻 Catalyst"
        )


        if result["Headlines"]:

            for headline in result[
                "Headlines"
            ]:

                st.write(
                    "•",
                    headline
                )

        else:

            st.write(
                "目前没有抓到足够近期新闻。"
            )


        st.caption(
            """
CMS-100 是一个波段筛选模型。

它不是自动交易系统，也不是保证盈利的投资建议。

Catalyst 新闻评分目前采用关键词和新闻活跃度规则。
"""
        )


    except Exception as e:

        st.error(
            f"分析失败：{e}"
        )
