import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import time
from datetime import datetime, timezone


# =========================================================
# PAGE
# =========================================================

st.set_page_config(
    page_title="CMS-100 Stock Screener V3.1",
    page_icon="📈",
    layout="wide"
)

st.title("📈 CMS-100 Stock Screener V3.1")

st.caption(
    "Catalyst + Momentum + Setup + Relative Strength + Trade Plan"
)


# =========================================================
# SETTINGS
# =========================================================

BATCH_SIZE = 40
MAX_RETRIES = 3
RETRY_WAIT = [5, 15, 30]
BATCH_PAUSE = 1.5


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


BENCHMARK_TICKERS = [
    "SPY",
    "XLK",
    "XLV",
    "XLF",
    "XLY",
    "XLP",
    "XLI",
    "XLE",
    "XLB",
    "XLU",
    "XLRE",
    "XLC"
]


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
# SCORE FUNCTIONS
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
# SAFE SINGLE DOWNLOAD
# =========================================================

@st.cache_data(ttl=1800)
def safe_download_single(ticker, period="1y"):

    ticker = ticker.upper().strip()

    for attempt in range(MAX_RETRIES):

        try:

            df = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False
            )

            if df is not None and not df.empty:

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                return df.dropna(how="all")

        except Exception:
            pass

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_WAIT[attempt])

    return None


# =========================================================
# BATCH DOWNLOAD
# =========================================================

def split_chunks(items, size):

    for i in range(0, len(items), size):
        yield items[i:i + size]


@st.cache_data(ttl=1800)
def safe_batch_download(
    tickers_tuple,
    period="1y"
):

    tickers = list(tickers_tuple)

    all_data = {}

    chunks = list(
        split_chunks(
            tickers,
            BATCH_SIZE
        )
    )

    for chunk_number, chunk in enumerate(chunks):

        for attempt in range(MAX_RETRIES):

            try:

                df = yf.download(
                    tickers=chunk,
                    period=period,
                    interval="1d",
                    auto_adjust=True,
                    group_by="ticker",
                    progress=False,
                    threads=False,
                    timeout=20
                )

                if df is not None and not df.empty:

                    if isinstance(df.columns, pd.MultiIndex):

                        level0 = df.columns.get_level_values(0)

                        for ticker in chunk:

                            if ticker in level0:

                                try:

                                    temp = (
                                        df[ticker]
                                        .copy()
                                        .dropna(how="all")
                                    )

                                    if (
                                        not temp.empty
                                        and "Close" in temp.columns
                                    ):
                                        all_data[ticker] = temp

                                except Exception:
                                    pass

                    elif len(chunk) == 1:

                        ticker = chunk[0]

                        if "Close" in df.columns:
                            all_data[ticker] = df.copy()

                    break

            except Exception:
                pass

            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT[attempt])

        if chunk_number < len(chunks) - 1:
            time.sleep(BATCH_PAUSE)

    return all_data


# =========================================================
# CMS UNIVERSE 100
# =========================================================

@st.cache_data(ttl=86400)
def get_sp500_tickers():

    tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "META",
        "GOOGL", "TSLA", "AVGO", "AMD", "NFLX",
        "ORCL", "IBM", "DELL", "HPE", "SMCI",

        "CRM", "ADBE", "NOW", "PLTR", "PATH",
        "CRWD", "PANW", "FTNT", "DDOG", "NET",
        "SNOW", "MDB", "ZS", "OKTA", "TEAM",

        "QCOM", "MU", "INTC", "ARM", "MRVL",
        "AMAT", "LRCX", "KLAC", "ON", "MCHP",

        "JPM", "BAC", "WFC", "GS", "MS",
        "V", "MA", "AXP", "PYPL", "COIN",
        "HOOD", "SOFI", "XYZ", "NU", "IBKR",

        "LLY", "UNH", "ABBV", "MRK", "AMGN",
        "JNJ", "PFE", "GILD", "ISRG", "TMO",
        "TEM", "VEEV", "REGN", "VRTX", "DXCM",

        "XOM", "CVX", "COP", "CAT", "GE",
        "BA", "RTX", "LMT", "ETN", "VRT",
        "PLUG", "FCX", "SLB", "FSLR", "CEG",

        "WMT", "COST", "HD", "DIS", "UBER",
        "ABNB", "DASH", "BKNG", "SHOP", "MELI",
        "RBLX", "SPOT", "ROKU", "DUOL", "RDDT",

        "CRCL", "APP", "RKLB", "ASTS", "IONQ",
        "RGTI", "SOUN", "HIMS", "CAVA", "CVNA"
    ]

    return tickers


# =========================================================
# TECHNICAL CALCULATION
# =========================================================

def calculate_technical(
    ticker,
    df
):

    try:

        if df is None or len(df) < 200:
            return None

        close = (
            pd.to_numeric(
                df["Close"],
                errors="coerce"
            )
            .dropna()
        )

        high = pd.to_numeric(
            df["High"],
            errors="coerce"
        )

        low = pd.to_numeric(
            df["Low"],
            errors="coerce"
        )

        volume = pd.to_numeric(
            df["Volume"],
            errors="coerce"
        )

        if len(close) < 200:
            return None


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
            close.iloc[-1]
            / close.iloc[-21]
            - 1
        )


        dollar_volume = (
            price * avg_vol20
        )


        resistance = float(
            high.shift(1)
            .rolling(20)
            .max()
            .iloc[-1]
        )


        recent_low20 = float(
            low.shift(1)
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
        # TREND SCORE - MAX 20
        # =====================================================

        trend_score = 0

        if price > ma20:
            trend_score += 5

        if price > ma50:
            trend_score += 5

        if ma20 > ma50:
            trend_score += 5

        if price > ma200:
            trend_score += 5


        # =====================================================
        # BREAKOUT SCORE - MAX 20
        # =====================================================

        if (
            price > resistance
            and rvol >= 1.5
        ):
            breakout_score = 20

        elif (
            price > resistance
            and rvol >= 1.2
        ):
            breakout_score = 17

        elif price > resistance:
            breakout_score = 14

        elif price >= resistance * 0.98:
            breakout_score = 10

        elif price >= resistance * 0.95:
            breakout_score = 5

        else:
            breakout_score = 0


        # =====================================================
        # VOLUME SCORE - MAX 15
        # =====================================================

        volume_score = score_volume(
            rvol
        )


        # =====================================================
        # STOP
        # =====================================================

        stop = min(
            ma20,
            price - 1.5 * atr14
        )

        if stop >= price:
            stop = (
                price - 1.5 * atr14
            )


        risk = (
            price - stop
        )


        # =====================================================
        # TARGETS
        # =====================================================

        recent_range = max(
            resistance - recent_low20,
            2.0 * atr14
        )


        tp1 = (
            price + recent_range
        )

        tp2 = (
            price + 1.5 * recent_range
        )


        rr = (
            (tp1 - price) / risk
            if risk > 0
            else np.nan
        )


        rr_score = score_rr(
            rr
        )


        # =====================================================
        # TRADE PLAN / ENTRY ZONE
        # =====================================================

        entry_low = max(
            resistance,
            price - 0.50 * atr14
        )

        entry_high = (
            price + 0.50 * atr14
        )


        if entry_low > entry_high:

            entry_low = price

            entry_high = (
                price
                + 0.25 * atr14
            )


        breakout_extension = (
            (price - resistance) / atr14
            if atr14 > 0
            else np.nan
        )


        if price < resistance:

            entry_status = (
                "WAIT FOR BREAKOUT"
            )

        elif breakout_extension <= 0.50:

            entry_status = (
                "ENTRY ZONE"
            )

        elif breakout_extension <= 1.00:

            entry_status = (
                "EXTENDED"
            )

        else:

            entry_status = (
                "DO NOT CHASE"
            )


        # =====================================================
        # DATA QUALITY CHECK
        # =====================================================

        if abs(ret20) > 0.60:
            data_check = "CHECK"
        else:
            data_check = "OK"


        return {

            "Ticker": ticker,
            "Price": price,

            "MA20": ma20,
            "MA50": ma50,
            "MA200": ma200,

            "RVOL": rvol,
            "20D Return": ret20,

            "Dollar Volume":
                dollar_volume,

            "Resistance":
                resistance,

            "ATR14":
                atr14,

            "Entry Low":
                entry_low,

            "Entry High":
                entry_high,

            "Entry Status":
                entry_status,

            "Breakout Extension":
                breakout_extension,

            "Stop":
                stop,

            "TP1":
                tp1,

            "TP2":
                tp2,

            "R/R":
                rr,

            "Trend Score":
                trend_score,

            "Breakout Score":
                breakout_score,

            "Volume Score":
                volume_score,

            "R/R Score":
                rr_score,

            "Data Check":
                data_check
        }


    except Exception:
        return None


# =========================================================
# QUICK FILTER
# =========================================================

def passes_quick_filter(r):

    if r is None:
        return False

    if r["Price"] < 5:
        return False

    if r["Price"] <= r["MA20"]:
        return False

    if r["Price"] <= r["MA50"]:
        return False

    if r["Price"] <= r["MA200"]:
        return False

    if r["MA20"] <= r["MA50"]:
        return False

    if r["RVOL"] < 0.8:
        return False

    if (
        r["Dollar Volume"]
        < 20_000_000
    ):
        return False

    return True


# =========================================================
# COMPANY INFO
# =========================================================

@st.cache_data(ttl=21600)
def get_company_info(ticker):

    try:

        tk = yf.Ticker(ticker)

        info = tk.info or {}

        company = (
            info.get("shortName")
            or info.get("longName")
            or ticker
        )

        sector = (
            info.get("sector")
            or "Unknown"
        )

        market_cap = (
            info.get("marketCap")
            or np.nan
        )

        return (
            company,
            sector,
            market_cap
        )

    except Exception:

        return (
            ticker,
            "Unknown",
            np.nan
        )


# =========================================================
# NEWS SCORE - MAX 10
# =========================================================

@st.cache_data(ttl=3600)
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

    max_age = 14 * 86400


    for item in news:

        try:

            title = ""
            ts = None

            if isinstance(item, dict):

                title = (
                    item.get("title", "")
                    or ""
                )

                ts = item.get(
                    "providerPublishTime"
                )

                content = item.get(
                    "content"
                )

                if (
                    not title
                    and isinstance(
                        content,
                        dict
                    )
                ):

                    title = (
                        content.get(
                            "title",
                            ""
                        )
                        or ""
                    )

                    pub = content.get(
                        "pubDate"
                    )

                    if pub:

                        try:

                            ts = (
                                pd.Timestamp(pub)
                                .timestamp()
                            )

                        except Exception:
                            ts = None


            if not title:
                continue


            if (
                ts is None
                or now - ts <= max_age
            ):

                recent_titles.append(
                    title
                )


        except Exception:
            continue


    n = len(
        recent_titles
    )


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


    raw_score = min(
        20,
        base + bonus
    )


    catalyst_score = int(
        round(
            raw_score / 2
        )
    )


    return (
        catalyst_score,
        recent_titles[:8]
    )


# =========================================================
# BENCHMARK RETURNS
# =========================================================

@st.cache_data(ttl=1800)
def get_benchmark_returns():

    data = safe_batch_download(
        tuple(BENCHMARK_TICKERS),
        "3mo"
    )

    results = {}

    for ticker, df in data.items():

        try:

            close = (
                df["Close"]
                .dropna()
            )

            if len(close) >= 21:

                results[ticker] = float(
                    close.iloc[-1]
                    / close.iloc[-21]
                    - 1
                )

        except Exception:
            pass

    return results


# =========================================================
# SECTOR SCORE - MAX 5
# =========================================================

def get_sector_score(
    sector,
    benchmark_returns
):

    etf = SECTOR_ETF.get(
        sector
    )

    if not etf:
        return 2, np.nan


    spy_ret = benchmark_returns.get(
        "SPY",
        np.nan
    )

    sector_ret = benchmark_returns.get(
        etf,
        np.nan
    )


    if (
        pd.isna(spy_ret)
        or pd.isna(sector_ret)
    ):
        return 2, np.nan


    relative_return = (
        sector_ret - spy_ret
    )


    if relative_return >= 0.05:
        score = 5

    elif relative_return >= 0.02:
        score = 4

    elif relative_return >= 0:
        score = 3

    elif relative_return >= -0.03:
        score = 1

    else:
        score = 0


    return (
        score,
        relative_return
    )


# =========================================================
# FINAL CMS
# =========================================================

def build_final_score(
    technical,
    benchmark_returns
):

    ticker = technical[
        "Ticker"
    ]


    company, sector, market_cap = (
        get_company_info(
            ticker
        )
    )


    sector_score, sector_relative = (
        get_sector_score(
            sector,
            benchmark_returns
        )
    )


    # =====================================================
    # RELATIVE STRENGTH - MAX 15
    # =====================================================

    spy_return = benchmark_returns.get(
        "SPY",
        np.nan
    )

    stock_return = technical.get(
        "20D Return",
        np.nan
    )


    if (
        pd.isna(spy_return)
        or pd.isna(stock_return)
    ):

        relative_strength = np.nan
        relative_strength_score = 7

    else:

        relative_strength = (
            stock_return - spy_return
        )


        if relative_strength >= 0.15:
            relative_strength_score = 15

        elif relative_strength >= 0.10:
            relative_strength_score = 13

        elif relative_strength >= 0.05:
            relative_strength_score = 10

        elif relative_strength >= 0.02:
            relative_strength_score = 7

        elif relative_strength >= 0:
            relative_strength_score = 4

        else:
            relative_strength_score = 0


    # =====================================================
    # CATALYST
    # =====================================================

    time.sleep(0.5)

    catalyst_score, headlines = (
        get_news_score(
            ticker
        )
    )


    # =====================================================
    # CMS TOTAL
    # =====================================================

    total_score = int(
        round(
            sector_score

            + catalyst_score

            + technical[
                "Trend Score"
            ]

            + technical[
                "Breakout Score"
            ]

            + technical[
                "Volume Score"
            ]

            + relative_strength_score

            + technical[
                "R/R Score"
            ]
        )
    )


    # =====================================================
    # GRADE
    # =====================================================

    if total_score >= 88:
        grade = "A+"

    elif total_score >= 82:
        grade = "A"

    elif total_score >= 78:
        grade = "B"

    elif total_score >= 70:
        grade = "C"

    else:
        grade = "PASS"


    # =====================================================
    # SIGNAL
    # =====================================================

    if (
        total_score >= 88

        and technical[
            "Trend Score"
        ] >= 15

        and technical[
            "Breakout Score"
        ] >= 17

        and technical[
            "RVOL"
        ] >= 1.5

        and technical[
            "R/R"
        ] >= 2.0
    ):

        signal = "STRONG BUY"


    elif (
        total_score >= 82

        and technical[
            "Trend Score"
        ] >= 15

        and technical[
            "Breakout Score"
        ] >= 10

        and technical[
            "RVOL"
        ] >= 1.0

        and technical[
            "R/R"
        ] >= 1.5
    ):

        signal = "BUY SETUP"


    elif (
        total_score >= 78

        and technical[
            "Trend Score"
        ] >= 15
    ):

        signal = "READY"


    elif total_score >= 70:

        signal = "EARLY WATCH"


    else:

        signal = "PASS"


    result = technical.copy()


    result.update({

        "Company":
            company,

        "Sector":
            sector,

        "Market Cap":
            market_cap,

        "Sector Score":
            sector_score,

        "Sector Relative":
            sector_relative,

        "Catalyst Score":
            catalyst_score,

        "Relative Strength":
            relative_strength,

        "Relative Strength Score":
            relative_strength_score,

        "CMS":
            total_score,

        "Grade":
            grade,

        "Signal":
            signal,

        "Headlines":
            headlines
    })


    return result


# =========================================================
# SINGLE STOCK
# =========================================================

def analyze_single_stock(ticker):

    ticker = (
        ticker
        .upper()
        .strip()
    )


    df = safe_download_single(
        ticker,
        "1y"
    )


    if df is None:

        raise ValueError(
            "Yahoo Finance 暂时无法返回数据。"
        )


    technical = calculate_technical(
        ticker,
        df
    )


    if technical is None:

        raise ValueError(
            "股票历史数据不足。"
        )


    benchmarks = (
        get_benchmark_returns()
    )


    return build_final_score(
        technical,
        benchmarks
    )


# =========================================================
# TABS
# =========================================================

tab1, tab2 = st.tabs(
    [
        "🔎 Single Stock",
        "🚀 Market Scanner"
    ]
)


# =========================================================
# SINGLE STOCK TAB
# =========================================================

with tab1:

    st.subheader(
        "单只股票分析"
    )


    ticker = st.text_input(
        "输入股票代码",
        value="TEM",
        placeholder=(
            "TEM / PATH / NVDA / PLTR"
        )
    )


    if st.button(
        "开始分析",
        key="single"
    ):

        with st.spinner(
            "正在分析..."
        ):

            try:

                r = analyze_single_stock(
                    ticker
                )


                c1, c2, c3, c4 = (
                    st.columns(4)
                )


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


                st.subheader(
                    f"{r['Company']} ({r['Ticker']})"
                )


                score_df = pd.DataFrame(
                    {
                        "Module": [
                            "Trend",
                            "Breakout",
                            "Volume",
                            "Relative Strength",
                            "Risk / Reward",
                            "Catalyst",
                            "Sector"
                        ],

                        "Score": [
                            r["Trend Score"],
                            r["Breakout Score"],
                            r["Volume Score"],
                            r[
                                "Relative Strength Score"
                            ],
                            r["R/R Score"],
                            r["Catalyst Score"],
                            r["Sector Score"]
                        ],

                        "Maximum": [
                            20,
                            20,
                            15,
                            15,
                            15,
                            10,
                            5
                        ]
                    }
                )


                st.dataframe(
                    score_df,
                    hide_index=True,
                    use_container_width=True
                )


                st.subheader(
                    "🎯 Trade Plan"
                )


                c1, c2, c3, c4 = (
                    st.columns(4)
                )


                c1.metric(
                    "Current Price",
                    f"${r['Price']:.2f}"
                )

                c2.metric(
                    "Entry Zone",
                    f"${r['Entry Low']:.2f} – "
                    f"${r['Entry High']:.2f}"
                )

                c3.metric(
                    "Stop",
                    f"${r['Stop']:.2f}"
                )

                c4.metric(
                    "R/R",
                    f"{r['R/R']:.2f}"
                )


                c5, c6, c7 = (
                    st.columns(3)
                )


                c5.metric(
                    "TP1",
                    f"${r['TP1']:.2f}"
                )

                c6.metric(
                    "TP2",
                    f"${r['TP2']:.2f}"
                )

                c7.metric(
                    "Entry Status",
                    r["Entry Status"]
                )


                if (
                    r["Entry Status"]
                    == "ENTRY ZONE"
                ):

                    st.success(
                        "🟢 ENTRY ZONE"
                    )

                elif (
                    r["Entry Status"]
                    == "WAIT FOR BREAKOUT"
                ):

                    st.warning(
                        "🟡 WAIT FOR BREAKOUT"
                    )

                elif (
                    r["Entry Status"]
                    == "EXTENDED"
                ):

                    st.warning(
                        "🟠 EXTENDED"
                    )

                else:

                    st.error(
                        "🔴 DO NOT CHASE"
                    )


            except Exception as e:

                st.error(
                    f"分析失败：{e}"
                )


# =========================================================
# MARKET SCANNER
# =========================================================

with tab2:

    st.subheader(
        "🚀 CMS Universe 100 Scanner"
    )


    candidate_limit = st.slider(
        "进入完整 CMS 分析的股票数量",
        min_value=10,
        max_value=30,
        value=15,
        step=5
    )


    top_n = st.slider(
        "显示 Top N",
        min_value=5,
        max_value=20,
        value=10
    )


    if st.button(
        "🚀 Scan CMS Universe 100",
        key="scan"
    ):

        try:

            tickers = (
                get_sp500_tickers()
            )


            st.write(
                f"准备扫描 {len(tickers)} 只股票..."
            )


            progress = st.progress(0)

            status = st.empty()


            # =================================================
            # STEP 1
            # =================================================

            status.write(
                "① 正在批量下载市场数据..."
            )


            market_data = safe_batch_download(
                tuple(tickers),
                "1y"
            )


            st.write(
                f"成功取得 "
                f"{len(market_data)} "
                f"只股票的数据。"
            )


            progress.progress(35)


            # =================================================
            # STEP 2
            # =================================================

            status.write(
                "② 正在计算趋势、突破和成交量..."
            )


            technical_results = []


            for ticker, df in market_data.items():

                r = calculate_technical(
                    ticker,
                    df
                )


                if (
                    r is not None
                    and passes_quick_filter(r)
                ):

                    technical_results.append(
                        r
                    )


            if not technical_results:

                st.warning(
                    "没有股票通过基础筛选。"
                )

                st.stop()


            quick_df = pd.DataFrame(
                technical_results
            )


            progress.progress(55)


            st.write(
                f"基础筛选后剩余 "
                f"{len(quick_df)} 只股票。"
            )


            # =================================================
            # STEP 3
            # =================================================

            quick_df[
                "Return Rank"
            ] = (
                quick_df[
                    "20D Return"
                ]
                .rank(
                    pct=True
                )
            )


            quick_df[
                "RVOL Rank"
            ] = (
                quick_df[
                    "RVOL"
                ]
                .rank(
                    pct=True
                )
            )


            quick_df[
                "Technical Rank"
            ] = (
                quick_df[
                    "Return Rank"
                ] * 0.60

                +

                quick_df[
                    "RVOL Rank"
                ] * 0.40
            )


            finalists = (
                quick_df
                .sort_values(
                    "Technical Rank",
                    ascending=False
                )
                .head(
                    candidate_limit
                )
            )


            progress.progress(65)


            # =================================================
            # STEP 4
            # =================================================

            benchmark_returns = (
                get_benchmark_returns()
            )


            # =================================================
            # STEP 5
            # =================================================

            cms_results = []

            total_finalists = len(
                finalists
            )


            for position, (_, row) in enumerate(
                finalists.iterrows(),
                start=1
            ):

                ticker = row[
                    "Ticker"
                ]


                status.write(
                    f"CMS分析 {ticker} "
                    f"({position}/{total_finalists})"
                )


                try:

                    final = build_final_score(
                        row.to_dict(),
                        benchmark_returns
                    )


                    cms_results.append(
                        final
                    )

                except Exception:
                    continue


                progress.progress(
                    min(
                        65
                        + int(
                            30
                            * position
                            / total_finalists
                        ),
                        95
                    )
                )


                time.sleep(0.75)


            status.empty()


            if not cms_results:

                st.warning(
                    "没有完成完整 CMS 分析。"
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
                .reset_index(
                    drop=True
                )
            )


            result_df[
                "Rank"
            ] = (
                result_df.index + 1
            )


            progress.progress(100)


            st.success(
                "✅ 扫描完成"
            )


            # =================================================
            # TOP N
            # =================================================

            display_columns = [

                "Rank",
                "Ticker",
                "Company",
                "Sector",
                "CMS",
                "Grade",
                "Signal",
                "Price",
                "RVOL",
                "20D Return",
                "Relative Strength",
                "Trend Score",
                "Breakout Score",
                "Volume Score",
                "Relative Strength Score",
                "Catalyst Score",
                "R/R",
                "Entry Status",
                "Stop",
                "TP1",
                "TP2",
                "Data Check"
            ]


            actual_n = min(
                top_n,
                len(result_df)
            )


            top_df = (
                result_df[
                    display_columns
                ]
                .head(
                    top_n
                )
                .copy()
            )


            st.subheader(
                f"🏆 Top {actual_n} CMS Candidates"
            )


            st.dataframe(
                top_df.style.format(
                    {
                        "Price": "{:.2f}",
                        "RVOL": "{:.2f}",
                        "20D Return": "{:.1%}",
                        "Relative Strength": "{:.1%}",
                        "R/R": "{:.2f}",
                        "Stop": "{:.2f}",
                        "TP1": "{:.2f}",
                        "TP2": "{:.2f}"
                    }
                ),

                hide_index=True,
                use_container_width=True
            )


            # =================================================
            # DOWNLOAD TODAY'S RESULTS
            # =================================================

            save_df = top_df.copy()

            scan_date = datetime.now().strftime("%Y-%m-%d")

            save_df.insert(
                0,
                "Scan Date",
                scan_date
            )

            csv_data = save_df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                label="💾 Download Today's Top Results",
                data=csv_data,
                file_name=f"CMS_Top_{actual_n}_{scan_date}.csv",
                mime="text/csv",
                key="download_top_results"
            )


            # =================================================
            # ACTIONABLE
            # =================================================

            actionable_df = result_df[
                result_df[
                    "Signal"
                ].isin(
                    [
                        "STRONG BUY",
                        "BUY SETUP"
                    ]
                )
            ]


            st.subheader(
                "🟢 Actionable Setups"
            )


            if actionable_df.empty:

                st.info(
                    "今天没有 BUY SETUP 或 STRONG BUY。"
                )

            else:

                st.dataframe(
                    actionable_df[
                        display_columns
                    ].style.format(
                        {
                            "Price": "{:.2f}",
                            "RVOL": "{:.2f}",
                            "20D Return": "{:.1%}",
                            "Relative Strength": "{:.1%}",
                            "R/R": "{:.2f}",
                            "Stop": "{:.2f}",
                            "TP1": "{:.2f}",
                            "TP2": "{:.2f}"
                        }
                    ),

                    hide_index=True,
                    use_container_width=True
                )


                # =================================================
                # TRADE PLANS
                # =================================================

                st.subheader(
                    "🎯 Trade Plans"
                )


                for _, r in actionable_df.iterrows():

                    with st.expander(
                        f"{r['Ticker']} | "
                        f"{r['Signal']} | "
                        f"CMS {int(r['CMS'])}"
                    ):

                        c1, c2, c3, c4 = (
                            st.columns(4)
                        )


                        c1.metric(
                            "Current Price",
                            f"${r['Price']:.2f}"
                        )


                        c2.metric(
                            "Entry Zone",
                            f"${r['Entry Low']:.2f} – "
                            f"${r['Entry High']:.2f}"
                        )


                        c3.metric(
                            "Stop",
                            f"${r['Stop']:.2f}"
                        )


                        c4.metric(
                            "R/R",
                            f"{r['R/R']:.2f}"
                        )


                        c5, c6, c7 = (
                            st.columns(3)
                        )


                        c5.metric(
                            "TP1",
                            f"${r['TP1']:.2f}"
                        )


                        c6.metric(
                            "TP2",
                            f"${r['TP2']:.2f}"
                        )


                        c7.metric(
                            "RVOL",
                            f"{r['RVOL']:.2f}x"
                        )


                        status_value = (
                            r["Entry Status"]
                        )


                        if (
                            status_value
                            == "ENTRY ZONE"
                        ):

                            st.success(
                                "🟢 ENTRY ZONE — "
                                "价格接近理想突破区域。"
                            )


                        elif (
                            status_value
                            == "WAIT FOR BREAKOUT"
                        ):

                            st.warning(
                                "🟡 WAIT FOR BREAKOUT — "
                                "等待价格正式突破阻力位。"
                            )


                        elif (
                            status_value
                            == "EXTENDED"
                        ):

                            st.warning(
                                "🟠 EXTENDED — "
                                "股票很强，但已经偏离突破位。"
                            )


                        else:

                            st.error(
                                "🔴 DO NOT CHASE — "
                                "当前价格离突破位过远。"
                            )


                        st.markdown(
                            "**Why it qualified**"
                        )


                        st.write(
                            f"✓ CMS: "
                            f"{int(r['CMS'])}/100"
                        )

                        st.write(
                            f"✓ Trend: "
                            f"{int(r['Trend Score'])}/20"
                        )

                        st.write(
                            f"✓ Breakout: "
                            f"{int(r['Breakout Score'])}/20"
                        )

                        st.write(
                            f"✓ RVOL: "
                            f"{r['RVOL']:.2f}x"
                        )

                        st.write(
                            f"✓ Relative Strength vs SPY: "
                            f"{r['Relative Strength']:.1%}"
                        )

                        st.write(
                            f"✓ Risk / Reward: "
                            f"{r['R/R']:.2f}"
                        )


            # =================================================
            # READY
            # =================================================

            ready_df = result_df[
                result_df[
                    "Signal"
                ] == "READY"
            ]


            st.subheader(
                "🟡 READY Candidates"
            )


            if ready_df.empty:

                st.write(
                    "目前没有 READY 股票。"
                )

            else:

                st.dataframe(
                    ready_df[
                        display_columns
                    ].style.format(
                        {
                            "Price": "{:.2f}",
                            "RVOL": "{:.2f}",
                            "20D Return": "{:.1%}",
                            "Relative Strength": "{:.1%}",
                            "R/R": "{:.2f}",
                            "Stop": "{:.2f}",
                            "TP1": "{:.2f}",
                            "TP2": "{:.2f}"
                        }
                    ),

                    hide_index=True,
                    use_container_width=True
                )


        except Exception as e:

            st.error(
                f"""
扫描暂时失败。

错误信息：

{e}

如果出现 403，请不要连续点击 Scan。
"""
            )


# =========================================================
# CACHE
# =========================================================

st.divider()


col1, col2 = st.columns(
    [1, 4]
)


with col1:

    if st.button(
        "🧹 Clear Cache"
    ):

        st.cache_data.clear()

        st.success(
            "缓存已清除"
        )


with col2:

    st.caption(
        "平常不要清除缓存，"
        "缓存可以降低 Yahoo 请求次数。"
    )


st.divider()


st.caption(
    """
CMS-100 V3.1 为实验性股票筛选工具，不构成投资建议。

CMS Signal 判断股票质量；
Entry Status 判断当前价格是否适合追入。

BUY SETUP 不等同于立即买入。
"""
)
