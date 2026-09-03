import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import time
from datetime import datetime, timezone, timedelta

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None


# =========================================================
# PAGE
# =========================================================

st.set_page_config(
    page_title="CMS-100 Stock Screener V4.2.1 Dual Engine",
    page_icon="📈",
    layout="wide"
)

st.title("📈 CMS-100 Stock Screener V4.2.1 Dual Engine")

st.caption(
    "Catalyst + Momentum + Setup + Relative Strength + Early Setup + Trade Plan"
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
        # V4 EARLY SETUP INDICATORS
        # =====================================================

        distance_to_resistance = (
            (resistance - price) / resistance
            if resistance > 0
            else np.nan
        )

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)

        rsi14 = float(
            (100 - (100 / (1 + rs))).iloc[-1]
        )

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()

        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        macd_value = float(macd_line.iloc[-1])
        macd_signal_value = float(macd_signal.iloc[-1])
        macd_hist_value = float(macd_hist.iloc[-1])
        macd_hist_prev = float(macd_hist.iloc[-2])

        ma20_series = close.rolling(20).mean()

        ma20_slope_5d = (
            ma20_series.iloc[-1] / ma20_series.iloc[-6] - 1
            if len(ma20_series.dropna()) >= 6
            and ma20_series.iloc[-6] != 0
            else np.nan
        )

        avg_vol5 = float(
            volume.rolling(5).mean().iloc[-1]
        )

        volume_build_ratio = (
            avg_vol5 / avg_vol20
            if avg_vol20 > 0
            else np.nan
        )

        range5 = float(
            high.rolling(5).max().iloc[-1]
            - low.rolling(5).min().iloc[-1]
        )

        range20 = float(
            high.rolling(20).max().iloc[-1]
            - low.rolling(20).min().iloc[-1]
        )

        compression_ratio = (
            range5 / range20
            if range20 > 0
            else np.nan
        )


        # =====================================================
        # V4 EARLY SETUP SCORE - MAX 30
        # =====================================================

        early_distance_score = 0

        if price < resistance:

            if distance_to_resistance <= 0.01:
                early_distance_score = 8
            elif distance_to_resistance <= 0.02:
                early_distance_score = 7
            elif distance_to_resistance <= 0.03:
                early_distance_score = 5
            elif distance_to_resistance <= 0.05:
                early_distance_score = 3


        ma20_slope_score = 0

        if not pd.isna(ma20_slope_5d):

            if ma20_slope_5d >= 0.02:
                ma20_slope_score = 5
            elif ma20_slope_5d >= 0.01:
                ma20_slope_score = 4
            elif ma20_slope_5d > 0:
                ma20_slope_score = 2


        macd_score = 0

        if macd_hist_value > 0 and macd_hist_value > macd_hist_prev:
            macd_score = 5
        elif macd_line.iloc[-1] > macd_signal.iloc[-1]:
            macd_score = 4
        elif macd_hist_value > macd_hist_prev:
            macd_score = 2


        rsi_score = 0

        if not pd.isna(rsi14):

            if 55 <= rsi14 <= 68:
                rsi_score = 4
            elif 50 <= rsi14 < 55:
                rsi_score = 3
            elif 68 < rsi14 <= 72:
                rsi_score = 2


        volume_build_score = 0

        if not pd.isna(volume_build_ratio):

            if volume_build_ratio >= 1.20:
                volume_build_score = 4
            elif volume_build_ratio >= 1.05:
                volume_build_score = 3
            elif volume_build_ratio >= 0.95:
                volume_build_score = 1


        compression_score = 0

        if not pd.isna(compression_ratio):

            if compression_ratio <= 0.35:
                compression_score = 4
            elif compression_ratio <= 0.45:
                compression_score = 3
            elif compression_ratio <= 0.55:
                compression_score = 2


        early_setup_score = int(
            early_distance_score
            + ma20_slope_score
            + macd_score
            + rsi_score
            + volume_build_score
            + compression_score
        )

        if early_setup_score >= 24:
            early_setup_status = "PRIME EARLY SETUP"
        elif early_setup_score >= 19:
            early_setup_status = "EARLY SETUP"
        elif early_setup_score >= 14:
            early_setup_status = "BUILDING"
        else:
            early_setup_status = "PASS"


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
        # V4.2.1 EARLY ENGINE EXECUTION UPGRADE
        # =====================================================

        # -----------------------------------------------------
        # STRUCTURE-BASED EARLY BUY ZONE
        # -----------------------------------------------------
        # This zone is anchored to Resistance + ATR + MA20,
        # rather than following the current price each day.
        #
        # Upper edge sits just below resistance.
        # Lower edge is roughly 0.75 ATR below resistance,
        # but MA20 can act as a higher structural support floor.

        early_buy_high = resistance - 0.10 * atr14

        structural_low = resistance - 0.75 * atr14

        early_buy_low = max(
            ma20,
            structural_low
        )

        # Safety fallback if MA20 is already too close to/above resistance.
        if early_buy_low >= early_buy_high:
            early_buy_low = resistance - 0.75 * atr14
            early_buy_high = resistance - 0.10 * atr14

        # -----------------------------------------------------
        # BREAKOUT BUY ZONE
        # -----------------------------------------------------

        breakout_buy_low = resistance

        breakout_buy_high = (
            resistance + 0.50 * atr14
        )

        # -----------------------------------------------------
        # STOP
        # -----------------------------------------------------
        # Use a structural stop below MA20 / ATR support.

        early_stop = min(
            ma20 - 0.25 * atr14,
            resistance - 1.50 * atr14
        )

        # Keep stop safely below the Early Buy Zone.
        if early_stop >= early_buy_low:
            early_stop = early_buy_low - 0.75 * atr14

        # -----------------------------------------------------
        # TARGETS
        # -----------------------------------------------------
        # Anchor targets to resistance so they remain relatively stable
        # while the stock is still in the pre-breakout phase.

        early_target_range = max(
            resistance - recent_low20,
            2.0 * atr14
        )

        early_tp1 = (
            resistance + early_target_range
        )

        early_tp2 = (
            resistance + 1.50 * early_target_range
        )

        # -----------------------------------------------------
        # POTENTIAL R/R
        # -----------------------------------------------------
        # Conservative Early R/R:
        # assume entry near the TOP of the Early Buy Zone.

        potential_risk = (
            early_buy_high - early_stop
        )

        potential_reward = (
            early_tp1 - early_buy_high
        )

        potential_rr = (
            potential_reward / potential_risk
            if potential_risk > 0
            else np.nan
        )

        # Breakout R/R used internally for Buy Status.
        breakout_risk = (
            breakout_buy_high - early_stop
        )

        breakout_reward = (
            early_tp1 - breakout_buy_high
        )

        breakout_rr = (
            breakout_reward / breakout_risk
            if breakout_risk > 0
            else np.nan
        )

        # -----------------------------------------------------
        # COMPACT DISPLAY ZONES
        # -----------------------------------------------------

        early_buy_zone = (
            f"${early_buy_low:.2f} – ${early_buy_high:.2f}"
        )

        breakout_buy_zone = (
            f"${breakout_buy_low:.2f} – ${breakout_buy_high:.2f}"
        )

        # -----------------------------------------------------
        # CURRENT-PRICE R/R
        # -----------------------------------------------------
        # If current price is below the preferred Early Buy Zone,
        # buying cheaper can improve R/R. This is used for the
        # ATR-aware Near Early Entry status.

        current_risk = (
            price - early_stop
        )

        current_reward = (
            early_tp1 - price
        )

        current_rr = (
            current_reward / current_risk
            if current_risk > 0
            else np.nan
        )

        # Distance from current price to the lower edge of the
        # preferred Early Buy Zone, expressed in ATR units.
        near_entry_distance_atr = (
            (early_buy_low - price) / atr14
            if atr14 > 0
            else np.nan
        )


        # -----------------------------------------------------
        # BUY STATUS
        # -----------------------------------------------------
        # Setup Quality is the first gate.
        # BUILDING/PASS cannot produce a true entry signal.
        #
        # V4.2.1 improvement:
        # A stock slightly BELOW the Preferred Early Buy Zone
        # is no longer forced to WAIT. If it is within 0.25 ATR
        # and current-price R/R is acceptable, it becomes
        # NEAR EARLY ENTRY.

        if early_setup_status == "PASS":

            buy_status = "NO ENTRY"

        elif early_setup_status == "BUILDING":

            buy_status = "WATCH - BUILDING"

        else:

            # PRIME EARLY SETUP / EARLY SETUP only from here.
            if price < resistance:

                if (
                    early_buy_low
                    <= price
                    <= early_buy_high
                ):

                    if (
                        not pd.isna(potential_rr)
                        and potential_rr >= 2.0
                        and early_setup_status
                        == "PRIME EARLY SETUP"
                    ):

                        buy_status = (
                            "STRONG EARLY ENTRY"
                        )

                    elif (
                        not pd.isna(potential_rr)
                        and potential_rr >= 1.5
                    ):

                        buy_status = "EARLY ENTRY"

                    else:

                        buy_status = (
                            "WAIT - LOW R/R"
                        )

                elif price < early_buy_low:

                    if (
                        not pd.isna(near_entry_distance_atr)
                        and near_entry_distance_atr <= 0.25
                        and not pd.isna(current_rr)
                        and current_rr >= 1.5
                    ):

                        if (
                            early_setup_status
                            == "PRIME EARLY SETUP"
                            and current_rr >= 2.0
                        ):

                            buy_status = (
                                "STRONG NEAR EARLY ENTRY"
                            )

                        else:

                            buy_status = (
                                "NEAR EARLY ENTRY"
                            )

                    else:

                        buy_status = (
                            "WAIT - BELOW ENTRY ZONE"
                        )

                else:

                    buy_status = (
                        "WAIT FOR BREAKOUT"
                    )

            else:

                if (
                    price <= breakout_buy_high
                    and not pd.isna(breakout_rr)
                    and breakout_rr >= 1.5
                ):

                    buy_status = (
                        "BREAKOUT ENTRY"
                    )

                elif (
                    price
                    <= resistance + 1.0 * atr14
                ):

                    buy_status = "EXTENDED"

                else:

                    buy_status = "DO NOT CHASE"


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


        # =====================================================
        # V4.2.1 ACTION PRIORITY + DISTANCE TO ENTRY
        # =====================================================
        priority_map = {
            "STRONG EARLY ENTRY": (1, "P1 - STRONG EARLY ENTRY"),
            "STRONG NEAR EARLY ENTRY": (1, "P1 - STRONG NEAR EARLY ENTRY"),
            "EARLY ENTRY": (2, "P2 - EARLY ENTRY"),
            "BREAKOUT ENTRY": (2, "P2 - BREAKOUT ENTRY"),
            "NEAR EARLY ENTRY": (3, "P3 - NEAR EARLY ENTRY"),
            "WAIT FOR BREAKOUT": (4, "P4 - WAIT FOR BREAKOUT"),
            "WAIT - BELOW ENTRY ZONE": (5, "P5 - BELOW ENTRY ZONE"),
            "WATCH - BUILDING": (6, "P6 - BUILDING"),
            "WAIT - LOW R/R": (7, "P7 - LOW R/R"),
            "EXTENDED": (8, "P8 - EXTENDED"),
            "DO NOT CHASE": (9, "P9 - DO NOT CHASE"),
            "NO ENTRY": (10, "P10 - NO ENTRY"),
        }

        action_priority_rank, action_priority = priority_map.get(
            buy_status, (99, "P99 - REVIEW")
        )

        distance_to_entry_dollar = early_buy_low - price
        distance_to_entry_pct = (
            distance_to_entry_dollar / price
            if price > 0 else np.nan
        )


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

            "RSI14":
                rsi14,

            "MACD":
                macd_value,

            "MACD Signal":
                macd_signal_value,

            "MACD Histogram":
                macd_hist_value,

            "MA20 Slope 5D":
                ma20_slope_5d,

            "Volume Build Ratio":
                volume_build_ratio,

            "Compression Ratio":
                compression_ratio,

            "Distance to Resistance":
                distance_to_resistance,

            "Early Setup Score":
                early_setup_score,

            "Early Setup Status":
                early_setup_status,

            "Buy Status":
                buy_status,

            "Action Priority":
                action_priority,

            "Action Priority Rank":
                action_priority_rank,

            "Distance to Entry $":
                distance_to_entry_dollar,

            "Distance to Entry %":
                distance_to_entry_pct,

            "Early Buy Zone":
                early_buy_zone,

            "Breakout Buy Zone":
                breakout_buy_zone,

            "Potential R/R":
                potential_rr,

            "Current R/R":
                current_rr,

            "Near Entry Distance ATR":
                near_entry_distance_atr,

            "Breakout R/R":
                breakout_rr,

            "Early Buy Low":
                early_buy_low,

            "Early Buy High":
                early_buy_high,

            "Breakout Buy Low":
                breakout_buy_low,

            "Breakout Buy High":
                breakout_buy_high,

            "Early Stop":
                early_stop,

            "Early TP1":
                early_tp1,

            "Early TP2":
                early_tp2,

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
# V4 EARLY ENGINE FILTER
# =========================================================

def passes_early_filter(r):

    if r is None:
        return False

    if r["Price"] < 5:
        return False

    # Early engine is intentionally looser than the CMS engine.
    # We want stocks that are strengthening before the formal breakout.
    if r["Price"] <= r["MA20"]:
        return False

    if r["Price"] < r["MA50"] * 0.98:
        return False

    if r["Price"] < r["MA200"] * 0.98:
        return False

    if pd.isna(r.get("MA20 Slope 5D")) or r["MA20 Slope 5D"] <= 0:
        return False

    if pd.isna(r.get("Distance to Resistance")):
        return False

    if not (0 <= r["Distance to Resistance"] <= 0.05):
        return False

    if pd.isna(r["RVOL"]) or r["RVOL"] < 0.60:
        return False

    if r["Dollar Volume"] < 20_000_000:
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
# GOOGLE SHEETS PERFORMANCE TRACKER — V4.2.1
# =========================================================

TRACKER_WORKSHEET = "Tracker"

TRACKER_HEADERS = [
    "Scan Date", "Scan Time", "Ticker", "Company",
    "Action Priority", "Buy Status", "Signal Price",
    "Distance to Entry $", "Distance to Entry %",
    "Early Buy Zone", "Early Stop", "Early TP1", "Early TP2",
    "Potential R/R", "Current R/R",
    "Early Setup Score", "Early Setup Status",
    "CMS", "Signal", "Sector", "RSI14", "MACD Histogram",
    "MA20 Slope 5D", "Volume Build Ratio", "Compression Ratio", "RVOL",
    "5D Date", "5D Price", "5D Return",
    "10D Date", "10D Price", "10D Return",
    "20D Date", "20D Price", "20D Return",
    "Last Updated"
]


def _cell_value(value):
    """Convert pandas/numpy values into Google-Sheets-safe values."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def get_tracker_worksheet():
    """Connect to the permanent Google Sheet configured in Streamlit Secrets."""
    if gspread is None or Credentials is None:
        raise RuntimeError(
            "Google Sheets libraries are missing. Add gspread and google-auth "
            "to requirements.txt, then reboot the Streamlit app."
        )

    if "gcp_service_account" not in st.secrets:
        raise RuntimeError("Streamlit Secret [gcp_service_account] was not found.")

    if "tracker" not in st.secrets or "sheet_name" not in st.secrets["tracker"]:
        raise RuntimeError("Streamlit Secret [tracker].sheet_name was not found.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    service_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(service_info, scopes=scopes)
    client = gspread.authorize(creds)

    sheet_name = st.secrets["tracker"]["sheet_name"]
    book = client.open(sheet_name)

    try:
        ws = book.worksheet(TRACKER_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(
            title=TRACKER_WORKSHEET,
            rows=2000,
            cols=max(40, len(TRACKER_HEADERS) + 5),
        )

    current_headers = ws.row_values(1)
    if not current_headers:
        ws.append_row(TRACKER_HEADERS, value_input_option="USER_ENTERED")
    elif current_headers != TRACKER_HEADERS:
        # V4.2.1 owns the Tracker worksheet schema. Preserve data where possible
        # by only filling missing headers to the right, rather than deleting rows.
        missing = [h for h in TRACKER_HEADERS if h not in current_headers]
        if missing:
            new_headers = current_headers + missing
            ws.update(
                range_name=f"A1:{gspread.utils.rowcol_to_a1(1, len(new_headers))}",
                values=[new_headers],
            )

    return ws


def tracker_records_df(ws):
    values = ws.get_all_records(default_blank="")
    if not values:
        return pd.DataFrame(columns=TRACKER_HEADERS)
    return pd.DataFrame(values)


def save_snapshot_to_google_sheet(tracker_snapshot):
    """
    Permanently save today's Engine-2 snapshot.
    Same Scan Date + Ticker is updated rather than duplicated.
    Existing 5D/10D/20D performance fields are preserved.
    """
    ws = get_tracker_worksheet()
    all_values = ws.get_all_values()

    if not all_values:
        ws.append_row(TRACKER_HEADERS, value_input_option="USER_ENTERED")
        all_values = [TRACKER_HEADERS]

    headers = all_values[0]
    header_pos = {h: i for i, h in enumerate(headers)}

    # Ensure every V4.2.1 field exists.
    missing_headers = [h for h in TRACKER_HEADERS if h not in header_pos]
    if missing_headers:
        headers = headers + missing_headers
        ws.update(
            range_name=f"A1:{gspread.utils.rowcol_to_a1(1, len(headers))}",
            values=[headers],
        )
        header_pos = {h: i for i, h in enumerate(headers)}
        all_values = ws.get_all_values()

    existing = {}
    for row_num, row in enumerate(all_values[1:], start=2):
        scan_date = row[header_pos["Scan Date"]] if len(row) > header_pos["Scan Date"] else ""
        ticker = row[header_pos["Ticker"]] if len(row) > header_pos["Ticker"] else ""
        if scan_date and ticker:
            existing[(str(scan_date), str(ticker).upper())] = (row_num, row)

    saved = 0
    updated = 0
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for _, r in tracker_snapshot.iterrows():
        record = {
            "Scan Date": r.get("Scan Date", ""),
            "Scan Time": r.get("Scan Time", ""),
            "Ticker": r.get("Ticker", ""),
            "Company": r.get("Company", ""),
            "Action Priority": r.get("Action Priority", ""),
            "Buy Status": r.get("Buy Status", ""),
            "Signal Price": r.get("Price", ""),
            "Distance to Entry $": r.get("Distance to Entry $", ""),
            "Distance to Entry %": r.get("Distance to Entry %", ""),
            "Early Buy Zone": r.get("Early Buy Zone", ""),
            "Early Stop": r.get("Early Stop", ""),
            "Early TP1": r.get("Early TP1", ""),
            "Early TP2": r.get("Early TP2", ""),
            "Potential R/R": r.get("Potential R/R", ""),
            "Current R/R": r.get("Current R/R", ""),
            "Early Setup Score": r.get("Early Setup Score", ""),
            "Early Setup Status": r.get("Early Setup Status", ""),
            "CMS": r.get("CMS", ""),
            "Signal": r.get("Signal", ""),
            "Sector": r.get("Sector", ""),
            "RSI14": r.get("RSI14", ""),
            "MACD Histogram": r.get("MACD Histogram", ""),
            "MA20 Slope 5D": r.get("MA20 Slope 5D", ""),
            "Volume Build Ratio": r.get("Volume Build Ratio", ""),
            "Compression Ratio": r.get("Compression Ratio", ""),
            "RVOL": r.get("RVOL", ""),
            "Last Updated": now_text,
        }

        key = (str(record["Scan Date"]), str(record["Ticker"]).upper())

        if key in existing:
            row_num, old_row = existing[key]
            # Pad old row, then update signal fields only. Performance remains intact.
            row_out = list(old_row) + [""] * (len(headers) - len(old_row))
            for field, value in record.items():
                if field in header_pos:
                    row_out[header_pos[field]] = _cell_value(value)

            end_cell = gspread.utils.rowcol_to_a1(row_num, len(headers))
            ws.update(
                range_name=f"A{row_num}:{end_cell}",
                values=[row_out[:len(headers)]],
                value_input_option="USER_ENTERED",
            )
            updated += 1
        else:
            row_out = [""] * len(headers)
            for field, value in record.items():
                if field in header_pos:
                    row_out[header_pos[field]] = _cell_value(value)
            ws.append_row(row_out, value_input_option="USER_ENTERED")
            saved += 1

    return saved, updated


def _close_series_for_ticker(ticker, start_date, end_date):
    """Download adjusted daily closes for tracker performance calculations."""
    try:
        df = yf.download(
            ticker,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return pd.Series(dtype=float)

        if isinstance(df.columns, pd.MultiIndex):
            # yfinance can return either (Price, Ticker) or ticker-grouped columns.
            if "Close" in df.columns.get_level_values(0):
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
            elif ticker in df.columns.get_level_values(0):
                close = df[ticker]["Close"]
            else:
                return pd.Series(dtype=float)
        else:
            close = df["Close"]

        close = pd.to_numeric(close, errors="coerce").dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close
    except Exception:
        return pd.Series(dtype=float)


def update_google_tracker_performance():
    """
    Fill missing 5D/10D/20D prices and returns using the 5th, 10th and 20th
    trading day AFTER the saved Scan Date. Existing completed fields are retained.
    """
    ws = get_tracker_worksheet()
    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        return 0, 0

    headers = all_values[0]
    hp = {h: i for i, h in enumerate(headers)}
    required = [
        "Scan Date", "Ticker", "Signal Price",
        "5D Date", "5D Price", "5D Return",
        "10D Date", "10D Price", "10D Return",
        "20D Date", "20D Price", "20D Return", "Last Updated"
    ]
    missing = [h for h in required if h not in hp]
    if missing:
        raise RuntimeError("Tracker is missing columns: " + ", ".join(missing))

    pending_rows = []
    ticker_min_date = {}

    for row_num, row in enumerate(all_values[1:], start=2):
        row_pad = list(row) + [""] * (len(headers) - len(row))
        scan_date_text = row_pad[hp["Scan Date"]]
        ticker = str(row_pad[hp["Ticker"]]).upper().strip()
        signal_price_text = row_pad[hp["Signal Price"]]

        if not scan_date_text or not ticker or signal_price_text in ("", None):
            continue

        try:
            scan_date = pd.to_datetime(scan_date_text).normalize()
            signal_price = float(str(signal_price_text).replace(",", ""))
        except Exception:
            continue

        horizons_needed = []
        for n in (5, 10, 20):
            if row_pad[hp[f"{n}D Return"]] in ("", None):
                horizons_needed.append(n)

        if not horizons_needed:
            continue

        pending_rows.append((row_num, row_pad, scan_date, ticker, signal_price, horizons_needed))
        if ticker not in ticker_min_date or scan_date < ticker_min_date[ticker]:
            ticker_min_date[ticker] = scan_date

    if not pending_rows:
        return 0, 0

    today = pd.Timestamp.today().normalize()
    price_cache = {}

    for ticker, min_date in ticker_min_date.items():
        # Include enough calendar buffer before/after trading-day horizons.
        start = (min_date + pd.Timedelta(days=1)).to_pydatetime()
        end = (today + pd.Timedelta(days=2)).to_pydatetime()
        price_cache[ticker] = _close_series_for_ticker(ticker, start, end)
        time.sleep(0.25)

    rows_updated = 0
    fields_filled = 0
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row_num, row_pad, scan_date, ticker, signal_price, horizons_needed in pending_rows:
        close = price_cache.get(ticker, pd.Series(dtype=float))
        if close.empty:
            continue

        # Strictly AFTER the scan date.
        future = close[close.index.normalize() > scan_date]
        changed = False

        for n in horizons_needed:
            if len(future) >= n:
                target_date = future.index[n - 1]
                target_price = float(future.iloc[n - 1])
                target_return = target_price / signal_price - 1.0

                row_pad[hp[f"{n}D Date"]] = target_date.strftime("%Y-%m-%d")
                row_pad[hp[f"{n}D Price"]] = round(target_price, 4)
                row_pad[hp[f"{n}D Return"]] = round(target_return, 6)
                fields_filled += 1
                changed = True

        if changed:
            row_pad[hp["Last Updated"]] = now_text
            end_cell = gspread.utils.rowcol_to_a1(row_num, len(headers))
            ws.update(
                range_name=f"A{row_num}:{end_cell}",
                values=[row_pad[:len(headers)]],
                value_input_option="USER_ENTERED",
            )
            rows_updated += 1

    return rows_updated, fields_filled


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
                    "⚡ V4 Early Setup"
                )

                e1, e2, e3, e4 = st.columns(4)

                e1.metric(
                    "Early Setup Score",
                    f"{r['Early Setup Score']}/30"
                )

                e2.metric(
                    "Early Status",
                    r["Early Setup Status"]
                )

                e3.metric(
                    "RSI14",
                    f"{r['RSI14']:.1f}"
                )

                e4.metric(
                    "Distance to Resistance",
                    f"{r['Distance to Resistance']:.1%}"
                )

                e5, e6, e7 = st.columns(3)

                e5.metric(
                    "MA20 Slope 5D",
                    f"{r['MA20 Slope 5D']:.1%}"
                )

                e6.metric(
                    "Volume Build",
                    f"{r['Volume Build Ratio']:.2f}x"
                )

                e7.metric(
                    "Compression",
                    f"{r['Compression Ratio']:.2f}"
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
        "🚀 CMS V4 Dual-Engine Scanner"
    )

    st.caption(
        "Engine 1 = 已经形成趋势/突破的 CMS 候选；"
        "Engine 2 = 可能在突破前启动的 Early Setup 候选。"
    )

    c_limit1, c_limit2 = st.columns(2)

    with c_limit1:
        candidate_limit = st.slider(
            "CMS Engine：进入完整分析的股票数量",
            min_value=10,
            max_value=30,
            value=15,
            step=5
        )

    with c_limit2:
        early_candidate_limit = st.slider(
            "Early Engine：进入完整分析的股票数量",
            min_value=10,
            max_value=30,
            value=15,
            step=5
        )

    top_n = st.slider(
        "每个引擎显示 Top N",
        min_value=5,
        max_value=20,
        value=10
    )

    scan_clicked = st.button(
        "🚀 Scan CMS Universe 100",
        key="scan"
    )

    if scan_clicked:

        try:

            tickers = get_sp500_tickers()

            st.write(
                f"准备扫描 {len(tickers)} 只股票..."
            )

            progress = st.progress(0)
            status = st.empty()

            # =================================================
            # STEP 1 - MARKET DATA
            # =================================================

            status.write(
                "① 正在批量下载市场数据..."
            )

            market_data = safe_batch_download(
                tuple(tickers),
                "1y"
            )

            st.write(
                f"成功取得 {len(market_data)} 只股票的数据。"
            )

            progress.progress(30)

            # =================================================
            # STEP 2 - TWO DIFFERENT FILTERS
            # =================================================

            status.write(
                "② 正在运行 CMS Engine 和 Early Engine..."
            )

            cms_technical_results = []
            early_technical_results = []

            for ticker, df in market_data.items():

                r = calculate_technical(
                    ticker,
                    df
                )

                if r is None:
                    continue

                if passes_quick_filter(r):
                    cms_technical_results.append(r)

                if passes_early_filter(r):
                    early_technical_results.append(r)

            if (
                not cms_technical_results
                and not early_technical_results
            ):
                st.warning(
                    "两个引擎都没有找到候选股票。"
                )
                st.stop()

            st.write(
                f"CMS Engine 初筛：{len(cms_technical_results)} 只；"
                f" Early Engine 初筛：{len(early_technical_results)} 只。"
            )

            progress.progress(50)

            # =================================================
            # STEP 3 - CMS ENGINE RANK
            # =================================================

            if cms_technical_results:

                quick_df = pd.DataFrame(
                    cms_technical_results
                )

                quick_df["Return Rank"] = (
                    quick_df["20D Return"]
                    .rank(pct=True)
                )

                quick_df["RVOL Rank"] = (
                    quick_df["RVOL"]
                    .rank(pct=True)
                )

                quick_df["Technical Rank"] = (
                    quick_df["Return Rank"] * 0.60
                    + quick_df["RVOL Rank"] * 0.40
                )

                finalists = (
                    quick_df
                    .sort_values(
                        "Technical Rank",
                        ascending=False
                    )
                    .head(candidate_limit)
                )

            else:
                finalists = pd.DataFrame()

            # =================================================
            # STEP 4 - EARLY ENGINE RANK
            # =================================================

            if early_technical_results:

                early_quick_df = pd.DataFrame(
                    early_technical_results
                )

                # Rank by true early characteristics, not CMS momentum.
                early_finalists = (
                    early_quick_df
                    .sort_values(
                        [
                            "Action Priority Rank",
                            "Early Setup Score",
                            "Potential R/R",
                            "Distance to Resistance",
                            "Volume Build Ratio",
                            "MA20 Slope 5D"
                        ],
                        ascending=[
                            True,
                            False,
                            False,
                            True,
                            False,
                            False
                        ]
                    )
                    .head(early_candidate_limit)
                )

            else:
                early_finalists = pd.DataFrame()

            progress.progress(60)

            benchmark_returns = get_benchmark_returns()

            # =================================================
            # STEP 5 - FULL CMS ENGINE ANALYSIS
            # =================================================

            cms_results = []

            if not finalists.empty:

                total_finalists = len(finalists)

                for position, (_, row) in enumerate(
                    finalists.iterrows(),
                    start=1
                ):

                    ticker = row["Ticker"]

                    status.write(
                        f"CMS Engine：{ticker} "
                        f"({position}/{total_finalists})"
                    )

                    try:
                        final = build_final_score(
                            row.to_dict(),
                            benchmark_returns
                        )
                        cms_results.append(final)
                    except Exception:
                        continue

                    time.sleep(0.50)

            # =================================================
            # STEP 6 - FULL EARLY ENGINE ANALYSIS
            # =================================================

            early_results = []

            if not early_finalists.empty:

                total_early = len(early_finalists)

                for position, (_, row) in enumerate(
                    early_finalists.iterrows(),
                    start=1
                ):

                    ticker = row["Ticker"]

                    status.write(
                        f"Early Engine：{ticker} "
                        f"({position}/{total_early})"
                    )

                    try:
                        final = build_final_score(
                            row.to_dict(),
                            benchmark_returns
                        )
                        early_results.append(final)
                    except Exception:
                        continue

                    time.sleep(0.50)

            status.empty()
            progress.progress(100)

            if not cms_results and not early_results:
                st.warning(
                    "两个引擎都没有完成完整分析。"
                )
                st.stop()

            st.success(
                "✅ V4 Dual-Engine 扫描完成"
            )

            # =================================================
            # SHARED DISPLAY COLUMNS
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
                "Early Setup Score",
                "Early Setup Status",
                "RSI14",
                "Distance to Resistance",
                "R/R",
                "Entry Status",
                "Stop",
                "TP1",
                "TP2",
                "Data Check"
            ]

            # =================================================
            # ENGINE 1 - CMS TOP LIST
            # =================================================

            if cms_results:

                result_df = pd.DataFrame(cms_results)

                result_df = (
                    result_df
                    .sort_values(
                        ["CMS", "Trend Score", "RVOL"],
                        ascending=[False, False, False]
                    )
                    .reset_index(drop=True)
                )

                result_df["Rank"] = result_df.index + 1

                actual_n = min(top_n, len(result_df))

                top_df = (
                    result_df[display_columns]
                    .head(top_n)
                    .copy()
                )

                st.subheader(
                    f"🏆 Engine 1 — Top {actual_n} CMS Candidates"
                )

                st.caption(
                    "这张表寻找已经形成趋势、突破和动量的股票。"
                )

                st.dataframe(
                    top_df.style.format(
                        {
                            "Price": "{:.2f}",
                            "RVOL": "{:.2f}",
                            "20D Return": "{:.1%}",
                            "Relative Strength": "{:.1%}",
                            "RSI14": "{:.1f}",
                            "Distance to Resistance": "{:.1%}",
                            "R/R": "{:.2f}",
                            "Stop": "{:.2f}",
                            "TP1": "{:.2f}",
                            "TP2": "{:.2f}"
                        }
                    ),
                    hide_index=True,
                    use_container_width=True
                )

                scan_date = datetime.now().strftime(
                    "%Y-%m-%d"
                )

                cms_save_df = top_df.copy()
                cms_save_df.insert(
                    0,
                    "Scan Date",
                    scan_date
                )

                st.download_button(
                    label="💾 Download CMS Top Results",
                    data=cms_save_df.to_csv(
                        index=False
                    ).encode("utf-8-sig"),
                    file_name=(
                        f"CMS_V4_CMS_Top_{actual_n}_"
                        f"{scan_date}.csv"
                    ),
                    mime="text/csv",
                    key="download_cms_results"
                )

                actionable_df = result_df[
                    result_df["Signal"].isin(
                        ["STRONG BUY", "BUY SETUP"]
                    )
                ]

                st.subheader(
                    "🟢 CMS Actionable Setups"
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
                                "RSI14": "{:.1f}",
                                "Distance to Resistance": "{:.1%}",
                                "R/R": "{:.2f}",
                                "Stop": "{:.2f}",
                                "TP1": "{:.2f}",
                                "TP2": "{:.2f}"
                            }
                        ),
                        hide_index=True,
                        use_container_width=True
                    )

                ready_df = result_df[
                    result_df["Signal"] == "READY"
                ]

                st.subheader(
                    "🟡 CMS READY Candidates"
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
                                "RSI14": "{:.1f}",
                                "Distance to Resistance": "{:.1%}",
                                "R/R": "{:.2f}",
                                "Stop": "{:.2f}",
                                "TP1": "{:.2f}",
                                "TP2": "{:.2f}"
                            }
                        ),
                        hide_index=True,
                        use_container_width=True
                    )

            else:
                st.info(
                    "CMS Engine 今天没有完成候选分析。"
                )

            st.divider()

            # =================================================
            # ENGINE 2 - TRUE EARLY SETUP TOP LIST
            # =================================================

            if early_results:

                early_result_df = pd.DataFrame(
                    early_results
                )

                early_result_df = (
                    early_result_df
                    .sort_values(
                        [
                            "Early Setup Score",
                            "Distance to Resistance",
                            "Volume Build Ratio",
                            "MA20 Slope 5D"
                        ],
                        ascending=[
                            False,
                            True,
                            False,
                            False
                        ]
                    )
                    .reset_index(drop=True)
                )

                early_result_df["Rank"] = (
                    early_result_df.index + 1
                )

                early_actual_n = min(
                    top_n,
                    len(early_result_df)
                )

                early_columns = [
                    "Rank",
                    "Ticker",
                    "Company",
                    "Action Priority",
                    "Buy Status",
                    "Price",
                    "Distance to Entry $",
                    "Distance to Entry %",
                    "Early Buy Zone",
                    "Early Stop",
                    "Early TP1",
                    "Potential R/R",
                    "Current R/R",
                    "Breakout Buy Zone",
                    "Early TP2",
                    "Early Setup Score",
                    "Early Setup Status",
                    "Near Entry Distance ATR",
                    "Resistance",
                    "Distance to Resistance",
                    "CMS",
                    "Signal",
                    "Sector",
                    "RSI14",
                    "MACD Histogram",
                    "MA20 Slope 5D",
                    "Volume Build Ratio",
                    "Compression Ratio",
                    "RVOL",
                    "Data Check"
                ]

                early_top_df = (
                    early_result_df[early_columns]
                    .head(top_n)
                    .copy()
                )

                st.subheader(
                    f"⚡ Engine 2 — Top {early_actual_n} Early Setup Candidates"
                )

                st.caption(
                    "V4.2.1：按 Action Priority 优先排序；"
                    "执行信息前置：Buy Status → Price → Distance to Entry → "
                    "Early Buy Zone → Stop → TP1 → R/R。"
                )

                st.dataframe(
                    early_top_df.style.format(
                        {
                            "Price": "{:.2f}",
                            "Distance to Entry $": "{:+.2f}",
                            "Distance to Entry %": "{:+.2%}",
                            "Early Stop": "{:.2f}",
                            "Early TP1": "{:.2f}",
                            "Early TP2": "{:.2f}",
                            "Potential R/R": "{:.2f}",
                            "Current R/R": "{:.2f}",
                            "Near Entry Distance ATR": "{:.2f}",
                            "Resistance": "{:.2f}",
                            "Distance to Resistance": "{:.1%}",
                            "RSI14": "{:.1f}",
                            "MACD Histogram": "{:.3f}",
                            "MA20 Slope 5D": "{:.1%}",
                            "Volume Build Ratio": "{:.2f}",
                            "Compression Ratio": "{:.2f}",
                            "RVOL": "{:.2f}",
                            "Stop": "{:.2f}",
                            "TP1": "{:.2f}",
                            "TP2": "{:.2f}"
                        }
                    ),
                    hide_index=True,
                    use_container_width=True
                )

                scan_date = datetime.now().strftime(
                    "%Y-%m-%d"
                )

                early_save_df = early_top_df.copy()
                early_save_df.insert(
                    0,
                    "Scan Date",
                    scan_date
                )

                st.download_button(
                    label="💾 Download Early Setup Results",
                    data=early_save_df.to_csv(
                        index=False
                    ).encode("utf-8-sig"),
                    file_name=(
                        f"CMS_V4_2_Early_Top_{early_actual_n}_"
                        f"{scan_date}.csv"
                    ),
                    mime="text/csv",
                    key="download_early_results"
                )

                # =================================================
                # V4.2.1 PERMANENT GOOGLE SHEETS PERFORMANCE TRACKER
                # =================================================
                tracker_columns = [
                    "Ticker", "Company", "Action Priority", "Buy Status",
                    "Price", "Distance to Entry $", "Distance to Entry %",
                    "Early Buy Zone", "Early Stop", "Early TP1", "Early TP2",
                    "Potential R/R", "Current R/R",
                    "Early Setup Score", "Early Setup Status",
                    "CMS", "Signal", "Sector", "RSI14", "MACD Histogram",
                    "MA20 Slope 5D", "Volume Build Ratio",
                    "Compression Ratio", "RVOL"
                ]

                tracker_snapshot = early_top_df[
                    [c for c in tracker_columns if c in early_top_df.columns]
                ].copy()

                tracker_snapshot.insert(
                    0, "Scan Date", datetime.now().strftime("%Y-%m-%d")
                )
                tracker_snapshot.insert(
                    1, "Scan Time", datetime.now().strftime("%H:%M:%S")
                )

                # -------------------------------------------------
                # V4.2.1 FIX:
                # Save the latest scan into Session State so that
                # clicking another Streamlit button does not make
                # the scan results disappear on the rerun.
                # -------------------------------------------------
                st.session_state["last_early_top_df"] = early_top_df.copy()
                st.session_state["last_tracker_snapshot"] = tracker_snapshot.copy()
                st.session_state["last_scan_date"] = scan_date
                st.session_state["last_early_actual_n"] = early_actual_n

                st.markdown("#### 📊 Permanent Performance Tracker")
                st.caption(
                    "Save writes permanently to Google Sheets. "
                    "5D/10D/20D are the 5th/10th/20th trading-day closes "
                    "after the Scan Date, compared with the saved Signal Price."
                )

                t1, t2, t3 = st.columns(3)

                with t1:
                    if st.button(
                        "☁️ Save Today's Results to Google Sheet",
                        key="save_early_tracker_google"
                    ):
                        try:
                            with st.spinner("Saving permanently to Google Sheets..."):
                                saved_count, updated_count = save_snapshot_to_google_sheet(
                                    tracker_snapshot
                                )
                            st.success(
                                f"Saved permanently: {saved_count} new rows, "
                                f"{updated_count} same-day rows updated."
                            )
                        except Exception as e:
                            st.error(f"Google Sheet save failed: {e}")

                with t2:
                    if st.button(
                        "🔄 Update 5D / 10D / 20D",
                        key="update_google_tracker"
                    ):
                        try:
                            with st.spinner("Checking later trading-day prices..."):
                                rows_updated, fields_filled = update_google_tracker_performance()
                            if fields_filled > 0:
                                st.success(
                                    f"Updated {rows_updated} tracker rows; "
                                    f"filled {fields_filled} performance horizons."
                                )
                            else:
                                st.info(
                                    "No new 5D/10D/20D results are due yet, "
                                    "or all eligible results are already filled."
                                )
                        except Exception as e:
                            st.error(f"Performance update failed: {e}")

                with t3:
                    if st.button(
                        "📖 Load Tracker History",
                        key="load_google_tracker"
                    ):
                        try:
                            ws = get_tracker_worksheet()
                            hist = tracker_records_df(ws)
                            st.session_state["google_tracker_history"] = hist
                            st.success(f"Loaded {len(hist)} permanent tracker rows.")
                        except Exception as e:
                            st.error(f"Tracker load failed: {e}")

                if "google_tracker_history" in st.session_state:
                    hist = st.session_state["google_tracker_history"]
                    if hist is not None and not hist.empty:
                        show_cols = [
                            "Scan Date", "Ticker", "Company", "Buy Status",
                            "Signal Price", "Early Setup Score", "CMS",
                            "5D Return", "10D Return", "20D Return",
                            "Last Updated"
                        ]
                        show_cols = [c for c in show_cols if c in hist.columns]

                        display_hist = hist[show_cols].copy()
                        for col in ["5D Return", "10D Return", "20D Return"]:
                            if col in display_hist.columns:
                                display_hist[col] = pd.to_numeric(
                                    display_hist[col], errors="coerce"
                                )

                        st.dataframe(
                            display_hist.tail(100).iloc[::-1].style.format(
                                {
                                    "Signal Price": "{:.2f}",
                                    "5D Return": "{:+.2%}",
                                    "10D Return": "{:+.2%}",
                                    "20D Return": "{:+.2%}",
                                },
                                na_rep=""
                            ),
                            hide_index=True,
                            use_container_width=True
                        )

                prime_df = early_result_df[
                    early_result_df[
                        "Early Setup Status"
                    ].isin(
                        [
                            "PRIME EARLY SETUP",
                            "EARLY SETUP"
                        ]
                    )
                ]

                st.subheader(
                    "🔥 Highest-Priority Early Setups"
                )

                if prime_df.empty:
                    st.info(
                        "目前没有 PRIME EARLY SETUP 或 EARLY SETUP。"
                    )
                else:
                    st.dataframe(
                        prime_df[
                            early_columns
                        ].style.format(
                            {
                                "Price": "{:.2f}",
                                "Resistance": "{:.2f}",
                                "Distance to Resistance": "{:.1%}",
                                "RSI14": "{:.1f}",
                                "MACD Histogram": "{:.3f}",
                                "MA20 Slope 5D": "{:.1%}",
                                "Volume Build Ratio": "{:.2f}",
                                "Compression Ratio": "{:.2f}",
                                "RVOL": "{:.2f}",
                                "Stop": "{:.2f}",
                                "TP1": "{:.2f}",
                                "TP2": "{:.2f}"
                            }
                        ),
                        hide_index=True,
                        use_container_width=True
                    )

            else:
                st.info(
                    "Early Engine 今天没有完成候选分析。"
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
    # V4.2.1 — PERSIST LAST SCAN ACROSS BUTTON CLICKS
    # =========================================================
    # Streamlit reruns the script whenever a button is clicked.
    # The previous version kept the scan table only inside the
    # Scan button branch, so clicking Save made the table vanish
    # before the save action could be processed.
    #
    # On non-scan reruns, rebuild the Early table and tracker
    # controls from Session State.
    if (
        not scan_clicked
        and "last_early_top_df" in st.session_state
        and "last_tracker_snapshot" in st.session_state
    ):
        early_top_df = st.session_state["last_early_top_df"].copy()
        tracker_snapshot = st.session_state["last_tracker_snapshot"].copy()
        early_actual_n = st.session_state.get(
            "last_early_actual_n", len(early_top_df)
        )
        scan_date = st.session_state.get(
            "last_scan_date", datetime.now().strftime("%Y-%m-%d")
        )

        st.subheader(
            f"⚡ Last Scan — Top {early_actual_n} Early Setup Candidates"
        )
        st.caption(
            "V4.2.1：结果已保留。点击 Save / Update / Load 不会再让扫描结果消失。"
        )

        format_map = {
            "Price": "{:.2f}",
            "Distance to Entry $": "{:+.2f}",
            "Distance to Entry %": "{:+.2%}",
            "Early Stop": "{:.2f}",
            "Early TP1": "{:.2f}",
            "Early TP2": "{:.2f}",
            "Potential R/R": "{:.2f}",
            "Current R/R": "{:.2f}",
            "Near Entry Distance ATR": "{:.2f}",
            "Resistance": "{:.2f}",
            "Distance to Resistance": "{:.1%}",
            "RSI14": "{:.1f}",
            "MACD Histogram": "{:.3f}",
            "MA20 Slope 5D": "{:.1%}",
            "Volume Build Ratio": "{:.2f}",
            "Compression Ratio": "{:.2f}",
            "RVOL": "{:.2f}",
        }

        st.dataframe(
            early_top_df.style.format(
                {k: v for k, v in format_map.items() if k in early_top_df.columns}
            ),
            hide_index=True,
            use_container_width=True
        )

        early_save_df = early_top_df.copy()
        if "Scan Date" not in early_save_df.columns:
            early_save_df.insert(0, "Scan Date", scan_date)

        st.download_button(
            label="💾 Download Early Setup Results",
            data=early_save_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=(
                f"CMS_V4_2_1_Early_Top_{early_actual_n}_{scan_date}.csv"
            ),
            mime="text/csv",
            key="download_early_results"
        )

        st.markdown("#### 📊 Permanent Performance Tracker")
        st.caption(
            "Save 会永久写入 Google Sheets；"
            "Update 会补 5D / 10D / 20D；Load 会读取历史记录。"
        )

        t1, t2, t3 = st.columns(3)

        with t1:
            if st.button(
                "☁️ Save Today's Results to Google Sheet",
                key="save_early_tracker_google"
            ):
                try:
                    with st.spinner("Saving permanently to Google Sheets..."):
                        saved_count, updated_count = save_snapshot_to_google_sheet(
                            tracker_snapshot
                        )
                    st.success(
                        f"✅ Saved permanently: {saved_count} new rows, "
                        f"{updated_count} same-day rows updated."
                    )
                except Exception as e:
                    st.error(f"Google Sheet save failed: {e}")

        with t2:
            if st.button(
                "🔄 Update 5D / 10D / 20D",
                key="update_google_tracker"
            ):
                try:
                    with st.spinner("Checking later trading-day prices..."):
                        rows_updated, fields_filled = (
                            update_google_tracker_performance()
                        )
                    if fields_filled > 0:
                        st.success(
                            f"Updated {rows_updated} tracker rows; "
                            f"filled {fields_filled} performance horizons."
                        )
                    else:
                        st.info(
                            "No new 5D/10D/20D results are due yet, "
                            "or all eligible results are already filled."
                        )
                except Exception as e:
                    st.error(f"Performance update failed: {e}")

        with t3:
            if st.button(
                "📖 Load Tracker History",
                key="load_google_tracker"
            ):
                try:
                    ws = get_tracker_worksheet()
                    hist = tracker_records_df(ws)
                    st.session_state["google_tracker_history"] = hist
                    st.success(f"Loaded {len(hist)} permanent tracker rows.")
                except Exception as e:
                    st.error(f"Tracker load failed: {e}")

        if "google_tracker_history" in st.session_state:
            hist = st.session_state["google_tracker_history"]
            if hist is not None and not hist.empty:
                show_cols = [
                    "Scan Date", "Ticker", "Company", "Buy Status",
                    "Signal Price", "Early Setup Score", "CMS",
                    "5D Return", "10D Return", "20D Return",
                    "Last Updated"
                ]
                show_cols = [c for c in show_cols if c in hist.columns]

                display_hist = hist[show_cols].copy()

                for col in ["Signal Price", "5D Return", "10D Return", "20D Return"]:
                    if col in display_hist.columns:
                        display_hist[col] = pd.to_numeric(
                            display_hist[col], errors="coerce"
                        )

                hist_formats = {}
                if "Signal Price" in display_hist.columns:
                    hist_formats["Signal Price"] = "{:.2f}"
                for col in ["5D Return", "10D Return", "20D Return"]:
                    if col in display_hist.columns:
                        hist_formats[col] = "{:+.2%}"

                st.dataframe(
                    display_hist.tail(100).iloc[::-1].style.format(
                        hist_formats,
                        na_rep=""
                    ),
                    hide_index=True,
                    use_container_width=True
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
CMS-100 V4.2.1 Dual Engine 为实验性股票筛选工具，不构成投资建议。

CMS Signal 判断已经形成的趋势/突破质量；
Early Setup Status 判断股票是否处于潜在启动前阶段；
Entry Status 判断当前价格是否适合追入。

BUY SETUP 和 EARLY SETUP 都不等同于立即买入。
"""
)
