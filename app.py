import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import time
from datetime import datetime, timezone

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
    page_title="CMS Stock Screener V4.3A.3B-FIX1 — Strong Stock Backtest",
    page_icon="📈",
    layout="wide",
)

st.title("📈 CMS Stock Screener V4.3A.3B-FIX1 — Strong Stock Backtest")
st.caption(
    "盘后日K选股：市场结构 + 趋势动量 + 资金积累 + 领导力 + Catalyst。"
    "新增 Fundamental Confirmation：Quality / FCF / Debt / Valuation / Growth；"
    "基本面只做确认和 Confidence，不改变 Early V2 原100分。"
)

# =========================================================
# SETTINGS
# =========================================================
BATCH_SIZE = 40
MAX_RETRIES = 3
RETRY_WAIT = [5, 15, 30]
BATCH_PAUSE = 1.5
TOP_N_DEFAULT = 10

# V4.3A five-module weights — frozen first implementation.
WEIGHTS = {
    "structure": 25,
    "trend": 20,
    "accumulation": 20,
    "leadership": 20,
    "catalyst": 15,
}

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
    "SPY", "XLK", "XLV", "XLF", "XLY", "XLP",
    "XLI", "XLE", "XLB", "XLU", "XLRE", "XLC"
]

# Catalyst V2: broader positive and negative dictionaries.
# Title matching is intentionally transparent and editable.
POSITIVE_CATALYST = {
    "业绩超预期": [
        "earnings beat", "beats estimates", "beat estimates", "eps beat",
        "revenue beat", "record revenue", "record earnings", "profit jumps",
        "profit rises", "strong earnings", "better than expected",
    ],
    "上调指引": [
        "raises guidance", "raised guidance", "raises outlook", "raised outlook",
        "increases guidance", "boosts guidance", "higher forecast",
        "guidance above", "upbeat outlook",
    ],
    "分析师上调": [
        "upgrade", "upgraded", "price target raised", "raises price target",
        "initiates with buy", "initiated with buy", "outperform rating",
        "overweight rating",
    ],
    "监管/临床利好": [
        "fda approval", "fda approved", "approval", "approved",
        "breakthrough designation", "fast track", "positive trial",
        "meets primary endpoint", "met primary endpoint", "phase 3 success",
    ],
    "合同/订单": [
        "contract awarded", "wins contract", "won contract", "major contract",
        "government contract", "new order", "large order", "backlog rises",
        "strategic contract",
    ],
    "合作/产品": [
        "partnership", "strategic partnership", "collaboration", "launches",
        "product launch", "commercial launch", "new platform", "new product",
        "deployment", "expands partnership",
    ],
    "并购/资本行动": [
        "acquisition", "acquires", "merger", "strategic investment",
        "share buyback", "stock buyback", "repurchase program",
        "dividend increase", "raises dividend",
    ],
    "需求/扩张": [
        "strong demand", "demand surge", "capacity expansion", "expands capacity",
        "new facility", "market expansion", "expands into", "growth accelerates",
    ],
}

NEGATIVE_CATALYST = {
    "业绩/指引转弱": [
        "misses estimates", "missed estimates", "earnings miss", "revenue miss",
        "cuts guidance", "cut guidance", "lowers guidance", "lowered guidance",
        "cuts outlook", "lowers outlook", "weak outlook", "profit warning",
    ],
    "分析师下调": [
        "downgrade", "downgraded", "price target cut", "cuts price target",
        "underperform rating", "sell rating",
    ],
    "监管/临床风险": [
        "fda rejection", "rejected", "clinical hold", "trial failure",
        "misses primary endpoint", "failed trial", "safety concern",
    ],
    "融资/稀释": [
        "stock offering", "share offering", "secondary offering", "dilution",
        "dilutive", "convertible notes offering",
    ],
    "法律/经营风险": [
        "investigation", "lawsuit", "probe", "recall", "contract loss",
        "loses contract", "ceo departure", "ceo resigns", "bankruptcy",
    ],
}

# =========================================================
# UNIVERSE
# =========================================================
def get_universe():
    return [
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX", "ORCL", "IBM", "DELL", "HPE", "SMCI",
        "CRM", "ADBE", "NOW", "PLTR", "PATH", "CRWD", "PANW", "FTNT", "DDOG", "NET", "SNOW", "MDB", "ZS", "OKTA", "TEAM",
        "QCOM", "MU", "INTC", "ARM", "MRVL", "AMAT", "LRCX", "KLAC", "ON", "MCHP",
        "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "PYPL", "COIN", "HOOD", "SOFI", "XYZ", "NU", "IBKR",
        "LLY", "UNH", "ABBV", "MRK", "AMGN", "JNJ", "PFE", "GILD", "ISRG", "TMO", "TEM", "VEEV", "REGN", "VRTX", "DXCM",
        "XOM", "CVX", "COP", "CAT", "GE", "BA", "RTX", "LMT", "ETN", "VRT", "PLUG", "FCX", "SLB", "FSLR", "CEG",
        "WMT", "COST", "HD", "DIS", "UBER", "ABNB", "DASH", "BKNG", "SHOP", "MELI", "RBLX", "SPOT", "ROKU", "DUOL", "RDDT",
        "CRCL", "APP", "RKLB", "ASTS", "IONQ", "RGTI", "SOUN", "HIMS", "CAVA", "CVNA"
    ]

# =========================================================
# DOWNLOAD HELPERS
# =========================================================
def split_chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]

@st.cache_data(ttl=1800)
def safe_batch_download(tickers_tuple, period="1y"):
    tickers = list(tickers_tuple)
    all_data = {}
    for chunk in split_chunks(tickers, BATCH_SIZE):
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
                    timeout=25,
                )
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        for t in chunk:
                            try:
                                sub = df[t].copy().dropna(how="all")
                                if not sub.empty:
                                    all_data[t] = sub
                            except Exception:
                                pass
                    elif len(chunk) == 1:
                        all_data[chunk[0]] = df.dropna(how="all")
                    break
            except Exception:
                pass
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT[attempt])
        time.sleep(BATCH_PAUSE)
    return all_data

@st.cache_data(ttl=1800)
def safe_download_single(ticker, period="1y"):
    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=25,
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
# BASIC HELPERS
# =========================================================
def safe_num(v, default=np.nan):
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def pct_return(close, n):
    if len(close) <= n or close.iloc[-n-1] == 0:
        return np.nan
    return float(close.iloc[-1] / close.iloc[-n-1] - 1)


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# =========================================================
# TRUE SUPPORT / RESISTANCE ZONES
# =========================================================
def _swing_points(series, side=5, mode="high"):
    """Return local swing points with a centered 2*side+1 window."""
    window = 2 * side + 1
    if mode == "high":
        roll = series.rolling(window, center=True).max()
        mask = series.eq(roll)
    else:
        roll = series.rolling(window, center=True).min()
        mask = series.eq(roll)
    pts = []
    for idx, val in series[mask].dropna().items():
        pts.append((idx, float(val)))
    return pts


def _cluster_swings(points, tolerance_pct=0.018, min_separation_days=8):
    """Cluster price-near swing points into zones; de-duplicate touches close in time."""
    if not points:
        return []
    points = sorted(points, key=lambda x: x[1])
    raw = []
    for dt, price in points:
        placed = False
        for cluster in raw:
            center = np.median([p for _, p in cluster])
            if center > 0 and abs(price - center) / center <= tolerance_pct:
                cluster.append((dt, price))
                placed = True
                break
        if not placed:
            raw.append([(dt, price)])

    zones = []
    for cluster in raw:
        cluster = sorted(cluster, key=lambda x: x[0])
        filtered = []
        for dt, p in cluster:
            if not filtered:
                filtered.append((dt, p))
            else:
                try:
                    day_gap = (pd.Timestamp(dt) - pd.Timestamp(filtered[-1][0])).days
                except Exception:
                    day_gap = min_separation_days
                if day_gap >= min_separation_days:
                    filtered.append((dt, p))
        if len(filtered) >= 2:
            prices = [p for _, p in filtered]
            dates = [pd.Timestamp(d) for d, _ in filtered]
            zones.append({
                "low": float(np.min(prices)),
                "high": float(np.max(prices)),
                "center": float(np.median(prices)),
                "touches": int(len(filtered)),
                "first": min(dates),
                "last": max(dates),
                "span_days": int((max(dates) - min(dates)).days),
            })
    return zones


def _zone_strength(zone):
    if zone is None:
        return "无有效区域"
    t = zone["touches"]
    span = zone["span_days"]
    if t >= 4 and span >= 60:
        return "很强"
    if t >= 3 and span >= 30:
        return "强"
    if t >= 2:
        return "中等"
    return "弱"


def identify_market_structure(df, atr14, price):
    """
    Use ~1 year daily data to identify repeated swing-high/swing-low price zones.
    A 'major' zone needs at least two separated touches.
    """
    hist = df.tail(252).copy()
    high = pd.to_numeric(hist["High"], errors="coerce")
    low = pd.to_numeric(hist["Low"], errors="coerce")
    close = pd.to_numeric(hist["Close"], errors="coerce")

    # Exclude the last 3 bars from swing clustering to reduce unstable edge pivots.
    core_high = high.iloc[:-3] if len(high) > 20 else high
    core_low = low.iloc[:-3] if len(low) > 20 else low

    swing_highs = _swing_points(core_high, side=5, mode="high")
    swing_lows = _swing_points(core_low, side=5, mode="low")

    # Tolerance scales modestly with volatility but is capped to avoid giant zones.
    atr_pct = atr14 / price if price > 0 and not pd.isna(atr14) else 0.015
    tol = float(np.clip(max(0.012, 0.65 * atr_pct), 0.012, 0.025))

    resistance_zones = _cluster_swings(swing_highs, tolerance_pct=tol)
    support_zones = _cluster_swings(swing_lows, tolerance_pct=tol)

    # Prefer nearest repeated resistance at/above current price.
    above = [z for z in resistance_zones if z["high"] >= price * 0.995]
    major_res = min(above, key=lambda z: max(z["low"] - price, 0)) if above else None

    below = [z for z in support_zones if z["low"] <= price * 1.005]
    major_sup = max(below, key=lambda z: z["center"]) if below else None

    # Recently broken resistance can become support (R→S flip).
    broken = [z for z in resistance_zones if z["high"] < price]
    flip_zone = max(broken, key=lambda z: z["center"]) if broken else None
    rs_flip = False
    if flip_zone is not None and atr14 > 0:
        # Price is no more than ~1 ATR above old resistance and last 5 closes stayed mostly above it.
        recent_closes = close.tail(5)
        above_count = int((recent_closes >= flip_zone["low"]).sum())
        rs_flip = (
            (price - flip_zone["high"]) <= 1.0 * atr14
            and above_count >= 4
        )

    short_breakout = safe_num(high.shift(1).rolling(20).max().iloc[-1])
    short_support = safe_num(low.shift(1).rolling(20).min().iloc[-1])

    return {
        "major_res": major_res,
        "major_sup": major_sup,
        "flip_zone": flip_zone,
        "rs_flip": rs_flip,
        "short_breakout": short_breakout,
        "short_support": short_support,
    }

# =========================================================
# MODULE 1 — MARKET STRUCTURE (MAX 25)
# =========================================================
def score_structure(df, price, atr14, structure):
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    close = pd.to_numeric(df["Close"], errors="coerce")

    major_res = structure["major_res"]
    short_breakout = structure["short_breakout"]

    # 1) Major resistance position + strength, max 10.
    major_score = 0
    major_distance = np.nan
    if major_res is not None:
        major_distance = (major_res["low"] - price) / price if price > 0 else np.nan
        touches = major_res["touches"]
        if -0.01 <= major_distance <= 0.035:
            major_score += 6
        elif 0.035 < major_distance <= 0.07:
            major_score += 3
        elif major_distance < -0.01:
            major_score += 2  # already above; may be a breakout/retest case
        major_score += min(4, max(0, touches - 1) * 2)
    elif structure["rs_flip"]:
        major_score = 6

    # 2) Short-term breakout proximity, max 5.
    short_score = 0
    short_distance = np.nan
    if not pd.isna(short_breakout) and short_breakout > 0:
        short_distance = (short_breakout - price) / short_breakout
        if 0.01 <= short_distance <= 0.03:
            short_score = 5
        elif 0 <= short_distance < 0.01:
            short_score = 4
        elif 0.03 < short_distance <= 0.05:
            short_score = 3
        elif -0.015 <= short_distance < 0:
            short_score = 4

    # 3) Compression quality, max 8.
    def norm_range(n):
        h = high.tail(n).max()
        l = low.tail(n).min()
        c = close.iloc[-1]
        return float((h - l) / c) if c > 0 else np.nan

    r5, r10, r20 = norm_range(5), norm_range(10), norm_range(20)
    compression_score = 0
    if not any(pd.isna(x) for x in [r5, r10, r20]):
        if r5 < r10 < r20:
            compression_score += 4
        elif r5 < r20 * 0.55:
            compression_score += 3
        elif r5 < r20 * 0.70:
            compression_score += 2

        ratio = r5 / r20 if r20 > 0 else np.nan
        if not pd.isna(ratio):
            if ratio <= 0.35:
                compression_score += 2
            elif ratio <= 0.50:
                compression_score += 1

    atr_series = calc_atr(high, low, close, 14)
    if len(atr_series.dropna()) >= 11:
        atr_now = atr_series.iloc[-1]
        atr_10 = atr_series.iloc[-11]
        if atr_10 > 0 and atr_now / atr_10 <= 0.90:
            compression_score += 2
        elif atr_10 > 0 and atr_now / atr_10 <= 1.00:
            compression_score += 1
    compression_score = min(8, compression_score)

    # 4) R→S flip confirmation, max 2.
    flip_score = 2 if structure["rs_flip"] else 0

    total = int(min(25, major_score + short_score + compression_score + flip_score))

    if major_res is not None:
        res_zone = f"${major_res['low']:.2f}–${major_res['high']:.2f}"
        res_touches = major_res["touches"]
        res_strength = _zone_strength(major_res)
    else:
        res_zone, res_touches, res_strength = "未识别", 0, "无有效区域"

    major_sup = structure["major_sup"]
    if major_sup is not None:
        sup_zone = f"${major_sup['low']:.2f}–${major_sup['high']:.2f}"
        sup_touches = major_sup["touches"]
    else:
        sup_zone, sup_touches = "未识别", 0

    compression_ratio = r5 / r20 if r20 and not pd.isna(r20) else np.nan

    flip_zone = structure.get("flip_zone")
    if flip_zone is not None:
        flip_zone_text = f"${flip_zone['low']:.2f}–${flip_zone['high']:.2f}"
        flip_touches = int(flip_zone.get("touches", 0))
    else:
        flip_zone_text = "未识别"
        flip_touches = 0

    return {
        "score": total,
        "Major Resistance Zone": res_zone,
        "Resistance Touches": res_touches,
        "Resistance Strength": res_strength,
        "Major Support Zone": sup_zone,
        "Support Touches": sup_touches,
        "Short-term Breakout": short_breakout,
        "Distance to Major Resistance": major_distance,
        "Distance to Short Breakout": short_distance,
        "Compression Ratio": compression_ratio,
        "R→S Flip": "是" if structure["rs_flip"] else "否",
        "R→S Flip Zone": flip_zone_text,
        "R→S Flip Touches": flip_touches,
    }

# =========================================================
# MODULE 2 — TREND & MOMENTUM (MAX 20)
# =========================================================
def score_trend_momentum(df):
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    price = float(close.iloc[-1])
    ma20_now = safe_num(ma20.iloc[-1])
    ma50_now = safe_num(ma50.iloc[-1])
    ma200_now = safe_num(ma200.iloc[-1])
    slope5 = ma20.iloc[-1] / ma20.iloc[-6] - 1 if len(ma20.dropna()) >= 6 and ma20.iloc[-6] else np.nan

    # MA20 slope max 8. >0.2% is the minimum meaningful rising threshold in V4.3A.
    slope_score = 0
    if not pd.isna(slope5):
        if 0.003 <= slope5 < 0.007:
            slope_score = 6
        elif 0.007 <= slope5 <= 0.015:
            slope_score = 8
        elif 0.002 <= slope5 < 0.003:
            slope_score = 4
        elif 0 < slope5 < 0.002:
            slope_score = 1
        elif slope5 > 0.015:
            slope_score = 6  # strong, but possibly becoming extended

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    m = safe_num(macd.iloc[-1])
    s = safe_num(signal.iloc[-1])
    h0 = safe_num(hist.iloc[-1])
    h1 = safe_num(hist.iloc[-2])
    h2 = safe_num(hist.iloc[-3])

    # MACD phase max 8.
    if m < 0 and h0 < 0 and h0 > h1 > h2:
        macd_phase, macd_score = "零轴下负柱连续缩短（提前转强）", 7
    elif m < 0 and m > s and h0 > 0:
        macd_phase, macd_score = "零轴下金叉（早期启动）", 8
    elif m >= 0 and m > s and h0 > 0 and h0 > h1:
        macd_phase, macd_score = "零轴上正柱扩大（确认强势）", 7
    elif m >= 0 and m > s and h0 > 0 and h0 < h1:
        macd_phase, macd_score = "零轴上正柱缩短（动能减弱）", 4
    elif h0 > h1:
        macd_phase, macd_score = "动能改善", 4
    elif m < s:
        macd_phase, macd_score = "偏弱/死叉", 1
    else:
        macd_phase, macd_score = "中性", 2

    rsi = safe_num(calc_rsi(close, 14).iloc[-1])
    if 52 <= rsi <= 68:
        rsi_score = 4
    elif 48 <= rsi < 52:
        rsi_score = 2
    elif 68 < rsi <= 72:
        rsi_score = 2
    else:
        rsi_score = 0

    total = int(min(20, slope_score + macd_score + rsi_score))
    return {
        "score": total,
        "MA20": ma20_now,
        "MA50": ma50_now,
        "MA200": ma200_now,
        "MA20 Slope 5D": slope5,
        "MACD": m,
        "MACD Signal": s,
        "MACD Histogram": h0,
        "MACD Phase": macd_phase,
        "RSI14": rsi,
        "Price": price,
    }

# =========================================================
# MODULE 3 — ACCUMULATION (MAX 20)
# =========================================================
def score_accumulation(df):
    close = pd.to_numeric(df["Close"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce")

    avg5 = safe_num(volume.rolling(5).mean().iloc[-1])
    avg20 = safe_num(volume.rolling(20).mean().iloc[-1])
    volume_build = avg5 / avg20 if avg20 > 0 else np.nan

    # Volume build max 7; very high volume is not automatically best.
    if pd.isna(volume_build):
        vb_score = 0
    elif 1.10 <= volume_build <= 1.80:
        vb_score = 7
    elif 0.95 <= volume_build < 1.10:
        vb_score = 4
    elif 1.80 < volume_build <= 2.50:
        vb_score = 5
    elif volume_build > 2.50:
        vb_score = 3
    else:
        vb_score = 1

    # Up-day vs down-day volume over last 10 bars, max 7.
    ret = close.pct_change()
    v10 = volume.tail(10)
    r10 = ret.tail(10)
    up_vol = float(v10[r10 > 0].sum())
    down_vol = float(v10[r10 < 0].sum())
    updown = up_vol / down_vol if down_vol > 0 else (3.0 if up_vol > 0 else np.nan)
    if pd.isna(updown):
        ud_score = 0
    elif updown >= 1.8:
        ud_score = 7
    elif updown >= 1.4:
        ud_score = 6
    elif updown >= 1.1:
        ud_score = 4
    elif updown >= 0.8:
        ud_score = 2
    else:
        ud_score = 0

    # OBV trend / positive divergence, max 6.
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume.fillna(0)).cumsum()
    obv_ma10 = obv.rolling(10).mean()
    obv_slope = obv.iloc[-1] - obv.iloc[-6] if len(obv) >= 6 else np.nan
    obv_up = bool(len(obv_ma10.dropna()) >= 2 and obv.iloc[-1] > obv_ma10.iloc[-1] and obv_slope > 0)

    price_20_high = close.tail(20).max()
    obv_20_high_prev = obv.shift(1).tail(20).max()
    positive_div = bool(
        len(close) >= 20
        and close.iloc[-1] < price_20_high * 0.995
        and obv.iloc[-1] >= obv_20_high_prev
    )

    obv_score = 0
    if obv_up:
        obv_score += 4
    if positive_div:
        obv_score += 2

    total = int(min(20, vb_score + ud_score + obv_score))
    return {
        "score": total,
        "Volume Build Ratio": volume_build,
        "Up/Down Volume Ratio": updown,
        "OBV Trend": "向上" if obv_up else "未确认",
        "OBV Positive Divergence": "是" if positive_div else "否",
    }

# =========================================================
# COMPANY INFO
# =========================================================
@st.cache_data(ttl=21600)
def get_company_info(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        return (
            info.get("shortName") or info.get("longName") or ticker,
            info.get("sector") or "Unknown",
            info.get("marketCap") or np.nan,
        )
    except Exception:
        return ticker, "Unknown", np.nan

# =========================================================
# FUNDAMENTAL CONFIRMATION — V4.3A.3
# Does NOT change Early V2 Score. It confirms company quality and risk.
# =========================================================
@st.cache_data(ttl=21600)
def get_fundamental_confirmation(ticker):
    """Return transparent fundamental checks using Yahoo Finance fields.

    This layer is intentionally separate from the Early V2 technical score.
    Missing fields are treated as '数据不足' rather than as an automatic fail.
    """
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}

    def n(key):
        return safe_num(info.get(key), np.nan)

    roe = n("returnOnEquity")
    op_margin = n("operatingMargins")
    profit_margin = n("profitMargins")
    fcf = n("freeCashflow")
    ocf = n("operatingCashflow")
    net_income = n("netIncomeToCommon")
    debt_equity = n("debtToEquity")
    total_debt = n("totalDebt")
    total_cash = n("totalCash")
    forward_pe = n("forwardPE")
    peg = n("pegRatio")
    ev_ebitda = n("enterpriseToEbitda")
    revenue_growth = n("revenueGrowth")
    earnings_growth = n("earningsGrowth")

    # ----- 1) Quality -----
    quality_pts = 0
    quality_obs = 0
    if not pd.isna(roe):
        quality_obs += 1
        quality_pts += 2 if roe >= 0.18 else (1 if roe >= 0.10 else 0)
    if not pd.isna(op_margin):
        quality_obs += 1
        quality_pts += 2 if op_margin >= 0.18 else (1 if op_margin >= 0.08 else 0)
    elif not pd.isna(profit_margin):
        quality_obs += 1
        quality_pts += 2 if profit_margin >= 0.15 else (1 if profit_margin >= 0.07 else 0)

    if quality_obs == 0:
        quality_status = "数据不足"
    elif quality_pts >= 3:
        quality_status = "Strong"
    elif quality_pts >= 1:
        quality_status = "Pass"
    else:
        quality_status = "Weak"

    # ----- 2) Cash flow -----
    cash_pts = 0
    cash_obs = 0
    if not pd.isna(fcf):
        cash_obs += 1
        cash_pts += 2 if fcf > 0 else 0
    if not pd.isna(ocf):
        cash_obs += 1
        cash_pts += 1 if ocf > 0 else 0
    if not pd.isna(ocf) and not pd.isna(net_income) and net_income > 0:
        cash_obs += 1
        cash_pts += 1 if ocf >= net_income * 0.8 else 0

    if cash_obs == 0:
        cash_status = "数据不足"
    elif cash_pts >= 3:
        cash_status = "Strong"
    elif cash_pts >= 1:
        cash_status = "Pass"
    else:
        cash_status = "Weak"

    # ----- 3) Debt / balance-sheet risk -----
    debt_obs = 0
    debt_pts = 0
    if not pd.isna(debt_equity):
        debt_obs += 1
        # Yahoo debtToEquity is commonly reported as a percentage (e.g. 50 = 50%).
        debt_pts += 2 if debt_equity <= 80 else (1 if debt_equity <= 150 else 0)
    if not pd.isna(total_debt) and not pd.isna(total_cash) and total_debt > 0:
        debt_obs += 1
        cash_debt = total_cash / total_debt
        debt_pts += 2 if cash_debt >= 0.75 else (1 if cash_debt >= 0.30 else 0)

    if debt_obs == 0:
        debt_status = "数据不足"
    elif debt_pts >= 3:
        debt_status = "Strong"
    elif debt_pts >= 1:
        debt_status = "Pass"
    else:
        debt_status = "Weak"

    # ----- 4) Valuation -----
    # Sector-relative valuation will be a later database/backtest enhancement.
    # V4.3A.3 only flags clearly stretched or reasonable absolute valuation.
    val_pts = 0
    val_obs = 0
    if not pd.isna(forward_pe) and forward_pe > 0:
        val_obs += 1
        val_pts += 2 if forward_pe <= 25 else (1 if forward_pe <= 45 else 0)
    if not pd.isna(peg) and peg > 0:
        val_obs += 1
        val_pts += 2 if peg <= 1.8 else (1 if peg <= 3.0 else 0)
    elif not pd.isna(ev_ebitda) and ev_ebitda > 0:
        val_obs += 1
        val_pts += 2 if ev_ebitda <= 18 else (1 if ev_ebitda <= 30 else 0)

    if val_obs == 0:
        valuation_status = "数据不足"
    elif val_pts >= 3:
        valuation_status = "Strong"
    elif val_pts >= 1:
        valuation_status = "Pass"
    else:
        valuation_status = "Weak"

    # ----- 5) Growth -----
    growth_pts = 0
    growth_obs = 0
    if not pd.isna(revenue_growth):
        growth_obs += 1
        growth_pts += 2 if revenue_growth >= 0.12 else (1 if revenue_growth >= 0.03 else 0)
    if not pd.isna(earnings_growth):
        growth_obs += 1
        growth_pts += 2 if earnings_growth >= 0.12 else (1 if earnings_growth >= 0.03 else 0)

    if growth_obs == 0:
        growth_status = "数据不足"
    elif growth_pts >= 3:
        growth_status = "Strong"
    elif growth_pts >= 1:
        growth_status = "Pass"
    else:
        growth_status = "Weak"

    statuses = [quality_status, cash_status, debt_status, valuation_status, growth_status]
    known = [x for x in statuses if x != "数据不足"]
    strong_n = sum(x == "Strong" for x in known)
    pass_n = sum(x == "Pass" for x in known)
    weak_n = sum(x == "Weak" for x in known)

    if len(known) < 3:
        overall = "数据不足"
    elif weak_n >= 2:
        overall = "Weak"
    elif strong_n >= 3 and weak_n == 0:
        overall = "Strong"
    elif strong_n + pass_n >= 3 and weak_n <= 1:
        overall = "Pass"
    else:
        overall = "Weak"

    reasons = []
    for label, status in [
        ("Quality", quality_status), ("FCF", cash_status), ("Debt", debt_status),
        ("Valuation", valuation_status), ("Growth", growth_status)
    ]:
        reasons.append(f"{label}:{status}")

    return {
        "Fundamental Confirmation": overall,
        "Fundamental Reason": " | ".join(reasons),
        "Quality Fundamental": quality_status,
        "FCF Fundamental": cash_status,
        "Debt Fundamental": debt_status,
        "Valuation Fundamental": valuation_status,
        "Growth Fundamental": growth_status,
        "ROE": roe,
        "Operating Margin": op_margin,
        "Free Cash Flow": fcf,
        "Operating Cash Flow": ocf,
        "Debt to Equity": debt_equity,
        "Forward PE": forward_pe,
        "PEG": peg,
        "EV/EBITDA": ev_ebitda,
        "Revenue Growth": revenue_growth,
        "Earnings Growth": earnings_growth,
    }


def final_confidence(row):
    """Combine technical readiness with fundamental confirmation without rescoring V4."""
    tech_score = row.get("Early V2 Score", 0)
    tech_gate = row.get("质量检查", "⚠️ 观察")
    f = row.get("Fundamental Confirmation", "数据不足")

    if f == "Weak":
        return "LOW"
    if tech_gate == "✅ 通过" and tech_score >= 78 and f == "Strong":
        return "HIGH"
    if tech_gate == "✅ 通过" and tech_score >= 72 and f in ("Strong", "Pass"):
        return "HIGH"
    if tech_score >= 62 and f in ("Strong", "Pass", "数据不足"):
        return "MEDIUM"
    return "LOW"

# =========================================================
# CATALYST V2 (MAX 15)
# =========================================================
@st.cache_data(ttl=3600)
def get_catalyst_v2(ticker):
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        return 0, "无明显催化", [], [], []

    now = datetime.now(timezone.utc).timestamp()
    max_age = 21 * 86400
    titles = []

    for item in news:
        try:
            title = item.get("title", "") if isinstance(item, dict) else ""
            ts = item.get("providerPublishTime") if isinstance(item, dict) else None
            content = item.get("content") if isinstance(item, dict) else None
            if not title and isinstance(content, dict):
                title = content.get("title", "") or ""
                pub = content.get("pubDate")
                if pub:
                    try:
                        ts = pd.Timestamp(pub).timestamp()
                    except Exception:
                        ts = None
            if title and (ts is None or now - ts <= max_age):
                titles.append(title)
        except Exception:
            continue

    text = " ".join(titles).lower()
    pos_cats = []
    neg_cats = []
    for cat, kws in POSITIVE_CATALYST.items():
        if any(kw in text for kw in kws):
            pos_cats.append(cat)
    for cat, kws in NEGATIVE_CATALYST.items():
        if any(kw in text for kw in kws):
            neg_cats.append(cat)

    # Positive categories are rewarded, negatives penalize harder.
    raw = min(15, len(pos_cats) * 4 + min(3, len(titles) // 3))
    raw -= min(15, len(neg_cats) * 6)
    score = int(np.clip(raw, 0, 15))

    if neg_cats and score <= 4:
        label = "负面催化风险"
    elif score >= 11:
        label = "强催化"
    elif score >= 6:
        label = "中等催化"
    elif score > 0:
        label = "轻度催化"
    else:
        label = "无明显催化"

    return score, label, pos_cats, neg_cats, titles[:6]

# =========================================================
# BENCHMARKS + MODULE 4 LEADERSHIP (MAX 20)
# =========================================================
@st.cache_data(ttl=1800)
def get_benchmark_returns():
    data = safe_batch_download(tuple(BENCHMARK_TICKERS), "3mo")
    out = {}
    for t, df in data.items():
        try:
            c = pd.to_numeric(df["Close"], errors="coerce").dropna()
            out[t] = {"5D": pct_return(c, 5), "20D": pct_return(c, 20)}
        except Exception:
            pass
    return out


def score_leadership(stock_ret5, stock_ret20, sector, benchmarks):
    spy = benchmarks.get("SPY", {})
    spy5, spy20 = spy.get("5D", np.nan), spy.get("20D", np.nan)
    sector_etf = SECTOR_ETF.get(sector)
    sec = benchmarks.get(sector_etf, {}) if sector_etf else {}
    sec5, sec20 = sec.get("5D", np.nan), sec.get("20D", np.nan)

    stock_vs_spy20 = stock_ret20 - spy20 if not pd.isna(stock_ret20) and not pd.isna(spy20) else np.nan
    sector_vs_spy20 = sec20 - spy20 if not pd.isna(sec20) and not pd.isna(spy20) else np.nan
    stock_vs_sector20 = stock_ret20 - sec20 if not pd.isna(stock_ret20) and not pd.isna(sec20) else np.nan
    stock_vs_spy5 = stock_ret5 - spy5 if not pd.isna(stock_ret5) and not pd.isna(spy5) else np.nan

    # Stock vs market max 8.
    if pd.isna(stock_vs_spy20):
        s1 = 3
    elif stock_vs_spy20 >= 0.10:
        s1 = 8
    elif stock_vs_spy20 >= 0.05:
        s1 = 7
    elif stock_vs_spy20 >= 0.02:
        s1 = 5
    elif stock_vs_spy20 >= 0:
        s1 = 3
    else:
        s1 = 0

    # Sector vs market max 6.
    if pd.isna(sector_vs_spy20):
        s2 = 2
    elif sector_vs_spy20 >= 0.05:
        s2 = 6
    elif sector_vs_spy20 >= 0.02:
        s2 = 5
    elif sector_vs_spy20 >= 0:
        s2 = 3
    elif sector_vs_spy20 >= -0.02:
        s2 = 1
    else:
        s2 = 0

    # Stock vs sector max 6.
    if pd.isna(stock_vs_sector20):
        s3 = 2
    elif stock_vs_sector20 >= 0.07:
        s3 = 6
    elif stock_vs_sector20 >= 0.03:
        s3 = 5
    elif stock_vs_sector20 >= 0:
        s3 = 3
    else:
        s3 = 0

    total = int(min(20, s1 + s2 + s3))
    accelerating = bool(
        not pd.isna(stock_vs_spy5)
        and not pd.isna(stock_vs_spy20)
        and stock_vs_spy5 > max(0.01, stock_vs_spy20 / 4)
    )

    return {
        "score": total,
        "Stock vs SPY 20D": stock_vs_spy20,
        "Sector vs SPY 20D": sector_vs_spy20,
        "Stock vs Sector 20D": stock_vs_sector20,
        "Stock vs SPY 5D": stock_vs_spy5,
        "RS Acceleration": "是" if accelerating else "否",
        "Sector ETF": sector_etf or "N/A",
    }

# =========================================================
# LEGACY CMS CONTEXT — SECONDARY, NOT PRIMARY RANKING
# =========================================================
def legacy_cms_context(row):
    trend = 0
    if row["Price"] > row["MA20"]: trend += 5
    if row["Price"] > row["MA50"]: trend += 5
    if row["MA20"] > row["MA50"]: trend += 5
    if row["Price"] > row["MA200"]: trend += 5

    breakout_ref = row["Short-term Breakout"]
    dist = row["Distance to Short Breakout"]
    rvol = row["RVOL"]
    if not pd.isna(breakout_ref) and row["Price"] > breakout_ref and rvol >= 1.5:
        breakout = 20
    elif not pd.isna(breakout_ref) and row["Price"] > breakout_ref:
        breakout = 14
    elif not pd.isna(dist) and dist <= 0.02:
        breakout = 10
    elif not pd.isna(dist) and dist <= 0.05:
        breakout = 5
    else:
        breakout = 0

    if pd.isna(rvol): volume = 0
    elif rvol >= 2: volume = 15
    elif rvol >= 1.5: volume = 12
    elif rvol >= 1.2: volume = 8
    elif rvol >= 0.8: volume = 4
    else: volume = 0

    # Re-map Early leadership/catalyst context into approximate old CMS scale.
    rs = min(15, round(row["Leadership Score"] * 0.75))
    cat = min(10, round(row["Catalyst Score"] * (10/15)))
    sector = min(5, round(max(0, row["Leadership Score"] - rs) * 0.5))
    total = int(min(100, trend + breakout + volume + rs + cat + sector + 10))
    return total

# =========================================================
# HARD FILTER + FINAL DAILY DECISION
# =========================================================
def passes_v43a_hard_filter(r):
    if r is None:
        return False, "数据不足"
    if r["Price"] < 5:
        return False, "股价低于$5"
    if r["Dollar Volume"] < 20_000_000:
        return False, "流动性不足"
    if r["Price"] < r["MA20"] * 0.99:
        return False, "价格明显低于MA20"
    if r["Price"] < r["MA50"] * 0.97:
        return False, "价格明显低于MA50"
    if r["Price"] < r["MA200"] * 0.95:
        return False, "价格明显低于MA200"
    if pd.isna(r["MA20 Slope 5D"]) or r["MA20 Slope 5D"] < 0.002:
        return False, "MA20斜率不足0.2%"
    if r["Structure Score"] < 8:
        return False, "市场结构不足"
    return True, "通过"


def daily_candidate_status(r):
    score = r["Early V2 Score"]
    core_ok = (
        r["Structure Score"] >= 12
        and r["Trend & Momentum Score"] >= 9
        and r["Accumulation Score"] >= 7
        and r["Leadership Score"] >= 6
    )
    negative_catalyst = r["Catalyst Label"] == "负面催化风险"

    if negative_catalyst:
        return "🔴 暂缓：存在负面催化"
    if score >= 82 and core_ok:
        return "🟢 一级重点候选"
    if score >= 72 and core_ok:
        return "🟢 二级重点候选"
    if score >= 62:
        return "🟡 观察候选"
    return "⚪ 暂缓"



def classify_structure_stage(row, structure_raw, atr14):
    """V4.3A.2: classify current structure transparently.

    A valid R→S retest must refer to an explicit historical resistance zone,
    and the current price must still be close enough to that flip zone.
    The nearest current major resistance is evaluated separately so that an
    old flip does not automatically override a poor current location.
    """
    price = float(row["Price"])
    major = structure_raw.get("major_res") if structure_raw else None
    flip = structure_raw.get("flip_zone") if structure_raw else None
    rs_flip = bool(structure_raw.get("rs_flip")) if structure_raw else False
    atr = atr14 if atr14 and not pd.isna(atr14) and atr14 > 0 else max(price * 0.02, 0.01)

    # ---- Explicit R→S validation ----
    flip_valid = False
    flip_reason = ""
    if rs_flip and flip is not None:
        flo, fhi = float(flip["low"]), float(flip["high"])
        dist_to_flip = max(price - fhi, 0.0)
        # Retest must be genuinely near the old resistance zone.
        if dist_to_flip <= 0.75 * atr and price >= flo * 0.995:
            flip_valid = True
            flip_reason = f"旧压力区 {flo:.2f}–{fhi:.2f} 已转为支撑并正在回踩"

    # If no current major resistance can be identified, a valid flip can still
    # be useful, but it remains an observation rather than an automatic pass.
    if major is None:
        if flip_valid:
            return "🟡 R→S回踩待确认", "观察", flip_reason + "；当前主要压力区未识别"
        return "⚪ 结构不明确", "观察", "当前未识别出可靠主要压力区"

    lo, hi = float(major["low"]), float(major["high"])

    # Current price below the nearest major resistance zone.
    if price < lo:
        gap = lo - price
        if flip_valid:
            # A valid old flip is supportive, but current overhead resistance
            # still matters. Only pass when the next major resistance is not too far.
            if gap <= 2.0 * atr:
                return "🟢 R→S回踩 + 接近压力", "通过", flip_reason + f"；下一主要压力区 {lo:.2f}–{hi:.2f}"
            return "🟡 R→S回踩但上方压力较远", "观察", flip_reason + f"；下一主要压力区 {lo:.2f}–{hi:.2f} 距离较远"
        if gap <= 1.0 * atr:
            return "🟢 压力下方蓄势", "通过", f"当前位于主要压力区 {lo:.2f}–{hi:.2f} 下方 1 ATR 内"
        if gap <= 2.5 * atr:
            return "🟡 接近主要压力", "观察", f"距离主要压力区 {lo:.2f}–{hi:.2f} 约 1–2.5 ATR"
        return "🔴 距压力过远", "不适合Early", f"距离主要压力区 {lo:.2f}–{hi:.2f} 超过 2.5 ATR"

    # Price currently inside the nearest major resistance zone.
    if lo <= price <= hi:
        if flip_valid:
            return "🟡 R→S有效，但正在测试新压力", "观察", flip_reason + f"；同时进入主要压力区 {lo:.2f}–{hi:.2f}"
        return "🟡 正在测试压力", "观察", f"当前价格位于主要压力区 {lo:.2f}–{hi:.2f} 内"

    # Price above the current major resistance zone.
    extension = price - hi
    if extension <= 0.75 * atr:
        return "🟡 突破待确认", "观察", f"刚突破主要压力区 {lo:.2f}–{hi:.2f}，等待确认或回踩"
    return "🔴 突破过远", "不适合Early", f"已高出主要压力区 {lo:.2f}–{hi:.2f} 超过 0.75 ATR"


def quality_gate(row):
    """Structure-first gate: score cannot rescue a poor Early-stage location."""
    stage_quality = row.get("结构质量", "观察")
    if row.get("Catalyst Label") == "负面催化风险":
        return "❌ 不适合Early", "负面催化风险"
    if stage_quality == "不适合Early":
        return "❌ 不适合Early", row.get("结构依据", row.get("结构阶段", "结构位置不理想"))
    if row["Structure Score"] < 10:
        return "❌ 不适合Early", "市场结构分过低"
    if row["Trend & Momentum Score"] < 8:
        return "⚠️ 观察", "趋势动量仍需加强"
    if stage_quality == "观察":
        return "⚠️ 观察", row.get("结构依据", row.get("结构阶段", "等待结构确认"))
    return "✅ 通过", row.get("结构依据", "结构位置适合Early候选")

# =========================================================
# PER-STOCK ANALYSIS
# =========================================================
def analyze_daily_candidate(ticker, df, benchmarks):
    try:
        if df is None or len(df) < 210:
            return None
        df = df.copy()
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["High", "Low", "Close", "Volume"])
        if len(df) < 210:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        price = float(close.iloc[-1])
        atr14 = safe_num(calc_atr(high, low, close, 14).iloc[-1])
        avgvol20 = safe_num(volume.rolling(20).mean().iloc[-1])
        rvol = float(volume.iloc[-1] / avgvol20) if avgvol20 > 0 else np.nan
        dollar_volume = price * avgvol20 if avgvol20 > 0 else 0
        ret5, ret20 = pct_return(close, 5), pct_return(close, 20)

        structure_raw = identify_market_structure(df, atr14, price)
        m1 = score_structure(df, price, atr14, structure_raw)
        m2 = score_trend_momentum(df)
        m3 = score_accumulation(df)

        company, sector, market_cap = get_company_info(ticker)
        fundamental = get_fundamental_confirmation(ticker)
        m4 = score_leadership(ret5, ret20, sector, benchmarks)
        cat_score, cat_label, pos_cats, neg_cats, headlines = get_catalyst_v2(ticker)

        total = int(m1["score"] + m2["score"] + m3["score"] + m4["score"] + cat_score)

        row = {
            "Ticker": ticker,
            "Company": company,
            "Sector": sector,
            "Market Cap": market_cap,
            "Price": price,
            "ATR14": atr14,
            "RVOL": rvol,
            "Dollar Volume": dollar_volume,
            "5D Return": ret5,
            "20D Return": ret20,

            "Structure Score": m1["score"],
            "Trend & Momentum Score": m2["score"],
            "Accumulation Score": m3["score"],
            "Leadership Score": m4["score"],
            "Catalyst Score": cat_score,
            "Early V2 Score": total,

            "Major Resistance Zone": m1["Major Resistance Zone"],
            "Resistance Touches": m1["Resistance Touches"],
            "Resistance Strength": m1["Resistance Strength"],
            "Major Support Zone": m1["Major Support Zone"],
            "Support Touches": m1["Support Touches"],
            "Short-term Breakout": m1["Short-term Breakout"],
            "Distance to Major Resistance": m1["Distance to Major Resistance"],
            "Distance to Short Breakout": m1["Distance to Short Breakout"],
            "Compression Ratio": m1["Compression Ratio"],
            "R→S Flip": m1["R→S Flip"],
            "R→S Flip Zone": m1["R→S Flip Zone"],
            "R→S Flip Touches": m1["R→S Flip Touches"],

            "MA20": m2["MA20"],
            "MA50": m2["MA50"],
            "MA200": m2["MA200"],
            "MA20 Slope 5D": m2["MA20 Slope 5D"],
            "MACD": m2["MACD"],
            "MACD Signal": m2["MACD Signal"],
            "MACD Histogram": m2["MACD Histogram"],
            "MACD Phase": m2["MACD Phase"],
            "RSI14": m2["RSI14"],

            "Volume Build Ratio": m3["Volume Build Ratio"],
            "Up/Down Volume Ratio": m3["Up/Down Volume Ratio"],
            "OBV Trend": m3["OBV Trend"],
            "OBV Positive Divergence": m3["OBV Positive Divergence"],

            "Stock vs SPY 20D": m4["Stock vs SPY 20D"],
            "Sector vs SPY 20D": m4["Sector vs SPY 20D"],
            "Stock vs Sector 20D": m4["Stock vs Sector 20D"],
            "Stock vs SPY 5D": m4["Stock vs SPY 5D"],
            "RS Acceleration": m4["RS Acceleration"],
            "Sector ETF": m4["Sector ETF"],

            **fundamental,

            "Catalyst Label": cat_label,
            "Positive Catalyst": "、".join(pos_cats) if pos_cats else "无",
            "Negative Catalyst": "、".join(neg_cats) if neg_cats else "无",
            "Headlines": " | ".join(headlines[:3]),
        }

        stage, structure_quality, structure_basis = classify_structure_stage(row, structure_raw, atr14)
        row["结构阶段"] = stage
        row["结构质量"] = structure_quality
        row["结构依据"] = structure_basis

        ok, reason = passes_v43a_hard_filter(row)
        row["Hard Filter"] = "通过" if ok else "未通过"
        row["Hard Filter Reason"] = reason
        q_status, q_reason = quality_gate(row) if ok else ("❌ 不适合Early", reason)
        row["质量检查"] = q_status
        row["质量原因"] = q_reason
        row["CMS Context"] = legacy_cms_context(row)
        row["次日决策"] = daily_candidate_status(row) if (ok and q_status == "✅ 通过") else ("🟡 观察候选" if ok and q_status == "⚠️ 观察" else f"⚪ 暂缓：{q_reason}")
        row["Confidence"] = final_confidence(row)
        return row
    except Exception:
        return None

# =========================================================
# GOOGLE SHEETS — NEW TAB, DOES NOT OVERWRITE V4.2.1 TRACKER
# =========================================================
DAILY_WORKSHEET = "A_Candidates"

A_SHEET_CN_MAP = {'Scan Date': '扫描日期', 'Scan Time': '扫描时间', 'Ticker': '股票代码', 'Company': '公司', 'Sector': '板块', 'Market Cap': '市值', 'Price': '价格', 'ATR14': 'ATR14', 'RVOL': 'RVOL', 'Dollar Volume': '成交额', '5D Return': '5日涨跌幅', '20D Return': '20日涨跌幅', 'Rank': '排名', 'Early V2 Score': 'Early V2总分', 'Confidence': '信心等级', 'Fundamental Confirmation': '基本面确认', 'Fundamental Reason': '基本面依据', 'Quality Fundamental': '质量', 'FCF Fundamental': '现金流', 'Debt Fundamental': '负债', 'Valuation Fundamental': '估值', 'Growth Fundamental': '增长', 'ROE': 'ROE', 'Operating Margin': '营业利润率', 'Free Cash Flow': '自由现金流', 'Operating Cash Flow': '经营现金流', 'Debt to Equity': 'Debt/Equity', 'Forward PE': 'Forward P/E', 'PEG': 'PEG', 'EV/EBITDA': 'EV/EBITDA', 'Revenue Growth': '营收增长', 'Earnings Growth': '盈利增长', 'Structure Score': '市场结构分', 'Trend & Momentum Score': '趋势动量分', 'Accumulation Score': '资金积累分', 'Leadership Score': '相对强势分', 'Catalyst Score': '催化剂分', 'Major Resistance Zone': '主要压力区', 'Resistance Touches': '压力测试次数', 'Resistance Strength': '压力强度', 'Major Support Zone': '主要支撑区', 'Support Touches': '支撑测试次数', 'Short-term Breakout': '短期突破位', 'Distance to Major Resistance': '距主要压力', 'Distance to Short Breakout': '距短期突破', 'Compression Ratio': '压缩比', 'R→S Flip': 'R→S转换', 'R→S Flip Zone': 'R→S回踩区', 'R→S Flip Touches': 'R→S历史测试次数', 'MA20': 'MA20', 'MA50': 'MA50', 'MA200': 'MA200', 'MA20 Slope 5D': 'MA20 5日斜率', 'MACD': 'MACD', 'MACD Signal': 'MACD信号', 'MACD Histogram': 'MACD柱', 'MACD Phase': 'MACD阶段', 'RSI14': 'RSI14', 'Volume Build Ratio': '量能增强比', 'Up/Down Volume Ratio': '涨跌量比', 'OBV Trend': 'OBV趋势', 'OBV Positive Divergence': 'OBV正背离', 'Stock vs SPY 20D': '个股 vs SPY 20日', 'Sector vs SPY 20D': '板块 vs SPY 20日', 'Stock vs Sector 20D': '个股 vs 板块 20日', 'Stock vs SPY 5D': '个股 vs SPY 5日', 'RS Acceleration': 'RS加速度', 'Sector ETF': '板块ETF', 'Catalyst Label': '催化剂状态', 'Positive Catalyst': '正面催化剂', 'Negative Catalyst': '负面催化剂', 'Headlines': '相关新闻', 'Hard Filter': '硬筛选', 'Hard Filter Reason': '硬筛选原因', 'CMS Context': 'CMS参考'}

def _cell(v):
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def get_daily_worksheet():
    if gspread is None or Credentials is None:
        raise RuntimeError("请在 requirements.txt 中保留 gspread 和 google-auth。")
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError("未找到 Streamlit Secret [gcp_service_account]。")
    if "tracker" not in st.secrets or "sheet_name" not in st.secrets["tracker"]:
        raise RuntimeError("未找到 [tracker].sheet_name。")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    client = gspread.authorize(creds)
    book = client.open(st.secrets["tracker"]["sheet_name"])
    try:
        ws = book.worksheet(DAILY_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=DAILY_WORKSHEET, rows=2000, cols=60)
    return ws


A_PRIMARY_COLS = [
    "Ticker", "Company", "Rank", "次日决策", "Early V2 Score", "Confidence",
    "Fundamental Confirmation", "Price", "结构阶段", "质量检查",
    "Major Resistance Zone", "Major Support Zone", "Short-term Breakout",
    "Structure Score", "Trend & Momentum Score", "Accumulation Score",
    "Leadership Score", "Catalyst Score", "Catalyst Label",
]


def reorder_a_columns(df):
    """Put decision-useful A columns first without dropping any original fields."""
    first = [c for c in A_PRIMARY_COLS if c in df.columns]
    rest = [c for c in df.columns if c not in first]
    return df[first + rest].copy()


def save_daily_candidates(df):
    ws = get_daily_worksheet()
    saved = df.copy()
    scan_date = datetime.now().strftime("%Y-%m-%d")
    scan_time = datetime.now().strftime("%H:%M:%S")
    saved.insert(0, "Scan Date", scan_date)
    saved.insert(1, "Scan Time", scan_time)

    fixed = ["Scan Date", "Scan Time"]
    primary = [c for c in A_PRIMARY_COLS if c in saved.columns]
    rest = [c for c in saved.columns if c not in fixed + primary]
    saved = saved[fixed + primary + rest].copy()
    sheet_df = saved.rename(columns=A_SHEET_CN_MAP)

    existing = ws.get_all_values()
    headers = list(sheet_df.columns)
    if not existing:
        ws.update("A1", [headers])
        existing = [headers]
    elif existing[0] != headers:
        ws.clear()
        ws.update("A1", [headers])
        existing = [headers]

    date_col, ticker_col = "扫描日期", "股票代码"
    date_idx, ticker_idx = headers.index(date_col), headers.index(ticker_col)
    row_map = {}
    for i, row in enumerate(existing[1:], start=2):
        if len(row) > max(date_idx, ticker_idx):
            row_map[(str(row[date_idx]), str(row[ticker_idx]).upper())] = i

    new_rows = updated_rows = 0
    for _, r in sheet_df.iterrows():
        values = [_cell(r.get(c, "")) for c in headers]
        key = (str(r[date_col]), str(r[ticker_col]).upper())
        if key in row_map:
            ws.update(f"A{row_map[key]}", [values])
            updated_rows += 1
        else:
            ws.append_row(values, value_input_option="USER_ENTERED")
            new_rows += 1
    return new_rows, updated_rows



# =========================================================
# A STRONG-STOCK HISTORY / BACKTEST — V4.3A.3B-FIX1
# Keeps LIVE A ranking unchanged. Stores the whole scanned universe so we can
# measure whether A ranks future 3–5 day big movers near the top.
# =========================================================
ALL_SCAN_WORKSHEET = "A_AllScannedHistory"

def get_named_worksheet(name, rows=12000, cols=80):
    if gspread is None or Credentials is None:
        raise RuntimeError("请在 requirements.txt 中保留 gspread 和 google-auth。")
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError("未找到 Streamlit Secret [gcp_service_account]。")
    if "tracker" not in st.secrets or "sheet_name" not in st.secrets["tracker"]:
        raise RuntimeError("未找到 [tracker].sheet_name。")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    client = gspread.authorize(creds)
    book = client.open(st.secrets["tracker"]["sheet_name"])
    try:
        return book.worksheet(name)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title=name, rows=rows, cols=cols)

def save_all_scanned_history(all_df):
    """Append/update every scanned stock, not only Top10. One row per scan-date+ticker."""
    ws = get_named_worksheet(ALL_SCAN_WORKSHEET)
    d = all_df.copy()
    d.insert(0, "Scan Date", datetime.now().strftime("%Y-%m-%d"))
    d.insert(1, "Scan Time", datetime.now().strftime("%H:%M:%S"))
    # Rank the whole universe with the same LIVE ordering logic.
    qorder = {"✅ 通过":0, "⚠️ 观察":1, "❌ 不适合Early":2}
    d["_q"] = d["质量检查"].map(qorder).fillna(9)
    d = d.sort_values(["_q","Early V2 Score","Structure Score","Leadership Score","Accumulation Score"],
                      ascending=[True,False,False,False,False]).drop(columns="_q").reset_index(drop=True)
    d["Universe Rank"] = d.index + 1
    keep = ["Scan Date","Scan Time","Ticker","Company","Sector","Universe Rank","Hard Filter","Hard Filter Reason",
            "质量检查","结构阶段","Early V2 Score","Structure Score","Trend & Momentum Score","Accumulation Score",
            "Leadership Score","Catalyst Score","Catalyst Label","Price","ATR14","RVOL","Dollar Volume",
            "MA20 Slope 5D","MACD Phase","RSI14","Volume Build Ratio","Up/Down Volume Ratio",
            "Stock vs SPY 20D","Sector vs SPY 20D","Stock vs Sector 20D","RS Acceleration","Confidence",
            "Fundamental Confirmation"]
    d=d[[c for c in keep if c in d.columns]].copy()
    headers=list(d.columns)
    existing=ws.get_all_values()
    if not existing:
        ws.update("A1", [headers]); existing=[headers]
    elif existing[0] != headers:
        # Backtest history is a derived diagnostic table. If an older test schema
        # exists, rebuild this worksheet automatically so the current version can
        # start collecting a clean, internally consistent full-universe history.
        ws.clear()
        ws.update("A1", [headers])
        existing = [headers]
    di=headers.index("Scan Date"); ti=headers.index("Ticker")
    rowmap={}
    for i,r in enumerate(existing[1:],start=2):
        if len(r)>max(di,ti): rowmap[(str(r[di]),str(r[ti]).upper())]=i
    new=upd=0
    for _,r in d.iterrows():
        vals=[_cell(r.get(c,"")) for c in headers]
        key=(str(r["Scan Date"]),str(r["Ticker"]).upper())
        if key in rowmap:
            ws.update(f"A{rowmap[key]}",[vals]); upd+=1
        else:
            ws.append_row(vals,value_input_option="USER_ENTERED"); new+=1
    return new,upd

def load_all_scan_history():
    ws=get_named_worksheet(ALL_SCAN_WORKSHEET)
    vals=ws.get_all_values()
    if len(vals)<2: return pd.DataFrame()
    return pd.DataFrame(vals[1:],columns=vals[0])

@st.cache_data(ttl=1800)
def download_backtest_daily(tickers_tuple):
    return safe_batch_download(tuple(tickers_tuple), "2y")

def evaluate_scan_history(hist, max_rows=1500):
    """Forward 1/3/5-trading-day outcome from scan close. No look-ahead in labels."""
    if hist is None or hist.empty: return pd.DataFrame()
    h=hist.copy().tail(max_rows)
    h["Scan Date"]=pd.to_datetime(h["Scan Date"],errors="coerce")
    h=h.dropna(subset=["Scan Date","Ticker"])
    tickers=tuple(sorted(h["Ticker"].astype(str).str.upper().unique()))
    px=download_backtest_daily(tickers)
    out=[]
    for _,r in h.iterrows():
        t=str(r["Ticker"]).upper(); df=px.get(t)
        if df is None or df.empty: continue
        d=df.copy(); d.index=pd.to_datetime(d.index).tz_localize(None) if getattr(pd.to_datetime(d.index), 'tz', None) is not None else pd.to_datetime(d.index)
        d=d.sort_index(); sd=pd.Timestamp(r["Scan Date"]).tz_localize(None)
        base_rows=d[d.index<=sd]
        future=d[d.index>sd].head(5)
        if base_rows.empty or future.empty: continue
        base=float(pd.to_numeric(base_rows["Close"],errors="coerce").iloc[-1])
        rec=dict(r); rec["Backtest Base Close"]=base
        for n in [1,3,5]:
            f=future.head(n)
            if f.empty: rec[f"{n}D Max Gain"]=np.nan; continue
            rec[f"{n}D Max Gain"]=float(pd.to_numeric(f["High"],errors="coerce").max()/base-1)
        if len(future)>=5:
            rec["5D Close Return"]=float(pd.to_numeric(future["Close"],errors="coerce").iloc[4]/base-1)
            rec["5D Max Drawdown"]=float(pd.to_numeric(future["Low"],errors="coerce").min()/base-1)
            g=rec.get("5D Max Gain",np.nan)
            rec["Hit +3%"] = bool(g>=0.03) if not pd.isna(g) else False
            rec["Hit +5%"] = bool(g>=0.05) if not pd.isna(g) else False
            rec["Hit +8%"] = bool(g>=0.08) if not pd.isna(g) else False
            rec["Strength Class"] = "🚀 ≥8%" if g>=.08 else ("🔥 5–8%" if g>=.05 else ("🟡 2–5%" if g>=.02 else "⚪ <2%"))
        else:
            rec["5D Close Return"]=np.nan; rec["5D Max Drawdown"]=np.nan
            rec["Hit +3%"] = rec["Hit +5%"] = rec["Hit +8%"] = False
            rec["Strength Class"]="等待5个交易日"
        out.append(rec)
    return pd.DataFrame(out)

def render_strong_stock_backtest(bt):
    mature=bt[pd.to_numeric(bt.get("5D Max Gain"),errors="coerce").notna()].copy() if not bt.empty else pd.DataFrame()
    if mature.empty:
        st.warning("还没有满5个交易日的全扫描池历史。先每天保存全部扫描池，5个交易日后就能开始正式比较。")
        return
    mature["Universe Rank"]=pd.to_numeric(mature["Universe Rank"],errors="coerce")
    g=pd.to_numeric(mature["5D Max Gain"],errors="coerce")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("样本",len(mature)); c2.metric("5日≥3%",f"{(g>=.03).mean():.1%}")
    c3.metric("5日≥5%",f"{(g>=.05).mean():.1%}"); c4.metric("5日≥8%",f"{(g>=.08).mean():.1%}")
    strong=mature[g>=.05]
    if len(strong):
        s1,s2,s3=st.columns(3)
        s1.metric("≥5%强股总数",len(strong))
        s2.metric("强股进入Top10",f"{(strong['Universe Rank']<=10).mean():.1%}")
        s3.metric("强股进入Top20",f"{(strong['Universe Rank']<=20).mean():.1%}")
    st.subheader("🚀 被A排低但后来大涨的股票")
    missed=mature[(g>=.05) & (mature["Universe Rank"]>10)].sort_values("5D Max Gain",ascending=False)
    cols=["Scan Date","Ticker","Universe Rank","Early V2 Score","Structure Score","Trend & Momentum Score","Accumulation Score","Leadership Score","Catalyst Score","5D Max Gain","5D Close Return","5D Max Drawdown"]
    st.dataframe(missed[[c for c in cols if c in missed.columns]].head(50),hide_index=True,use_container_width=True)
    st.subheader("📊 Top10 vs 全扫描池")
    rows=[]
    for label,x in [("全部扫描池",mature),("A Top10",mature[mature["Universe Rank"]<=10]),("A Top20",mature[mature["Universe Rank"]<=20])]:
        gg=pd.to_numeric(x["5D Max Gain"],errors="coerce")
        rows.append({"范围":label,"样本":len(x),"≥3%":(gg>=.03).mean() if len(x) else np.nan,"≥5%":(gg>=.05).mean() if len(x) else np.nan,"≥8%":(gg>=.08).mean() if len(x) else np.nan,"平均5日最大涨幅":gg.mean() if len(x) else np.nan})
    st.dataframe(pd.DataFrame(rows).style.format({"≥3%":"{:.1%}","≥5%":"{:.1%}","≥8%":"{:.1%}","平均5日最大涨幅":"{:.1%}"},na_rep=""),hide_index=True,use_container_width=True)

# =========================================================
# UI
# =========================================================
with st.sidebar:
    st.header("V4.3A.3 设置")
    top_n = st.slider("次日重点候选数量", min_value=5, max_value=20, value=TOP_N_DEFAULT, step=1)
    st.markdown("**Early Engine V2 权重**")
    st.write("市场结构 25")
    st.write("趋势动量 20")
    st.write("资金积累 20")
    st.write("领导力 20")
    st.write("Catalyst 15")
    st.markdown("**Fundamental Confirmation（不计入100分）**")
    st.write("Quality / FCF / Debt / Valuation / Growth")
    st.caption("A程序是盘后选股，不是盘中买入信号；基本面层只确认 Confidence。")

st.info(
    "V4.3A.3 运行逻辑：约1年日K → 五大模块 → Hard Filter → Fundamental Confirmation → Early V2排名 → 次日Top候选。"
    "V4.3B负责1H、15min和真正盘中买入/持仓管理信号。"
)

scan_clicked = st.button("🚀 运行 V4.3A 盘后扫描", type="primary", use_container_width=True)

if scan_clicked:
    tickers = get_universe()
    progress = st.progress(0)
    status = st.empty()

    status.write("正在下载约1年日K数据……")
    data = safe_batch_download(tuple(tickers), "1y")
    benchmarks = get_benchmark_returns()

    results = []
    for i, ticker in enumerate(tickers, start=1):
        status.write(f"正在分析 {ticker}（{i}/{len(tickers)}）")
        df = data.get(ticker)
        if df is None:
            df = safe_download_single(ticker, "1y")
        row = analyze_daily_candidate(ticker, df, benchmarks)
        if row is not None:
            results.append(row)
        progress.progress(int(i / len(tickers) * 100))

    status.empty()
    if not results:
        st.error("扫描没有得到有效结果，请稍后再试。")
        st.stop()

    all_df = pd.DataFrame(results)
    eligible = all_df[all_df["Hard Filter"] == "通过"].copy()
    quality_order = {"✅ 通过": 0, "⚠️ 观察": 1, "❌ 不适合Early": 2}
    eligible["_质量排序"] = eligible["质量检查"].map(quality_order).fillna(9)
    eligible = eligible.sort_values(
        ["_质量排序", "Early V2 Score", "Structure Score", "Leadership Score", "Accumulation Score"],
        ascending=[True, False, False, False, False],
    ).drop(columns=["_质量排序"]).reset_index(drop=True)
    eligible["Rank"] = eligible.index + 1
    top_df = eligible.head(top_n).copy()

    # Keep the latest result during Streamlit reruns.
    st.session_state["v43a_top_df"] = top_df.copy()
    st.session_state["v43a_all_df"] = all_df.copy()
    st.session_state["v43a_scan_date"] = datetime.now().strftime("%Y-%m-%d")
    # Full-universe history is kept separately for A strength backtesting.
    try:
        n_all, u_all = save_all_scanned_history(all_df)
        st.session_state["a_all_history_save_msg"] = f"全扫描池历史：新增 {n_all} 行，更新 {u_all} 行"
    except Exception as e:
        st.session_state["a_all_history_save_msg"] = f"全扫描池历史保存失败：{e}"


def render_results(top_df, all_df):
    if top_df is None or top_df.empty:
        st.warning("当前没有通过 V4.3A Hard Filter 的候选股票。")
        return

    st.success(f"✅ V4.3A.3 扫描完成：{len(top_df)}只次日重点候选")

    display_cols = [
        # 第一屏：真正用于每天判断/复核的字段
        "Rank", "Ticker", "Company", "次日决策", "Early V2 Score", "Confidence",
        "Fundamental Confirmation", "Price", "结构阶段", "质量检查",
        "Major Resistance Zone", "Major Support Zone", "Short-term Breakout",

        # 第二层：解释为什么入选
        "Fundamental Reason", "结构依据", "质量原因",
        "Structure Score", "Trend & Momentum Score", "Accumulation Score",
        "Leadership Score", "Catalyst Score", "Catalyst Label",

        # 其余诊断/明细
        "Quality Fundamental", "FCF Fundamental", "Debt Fundamental", "Valuation Fundamental", "Growth Fundamental",
        "Resistance Touches", "R→S Flip", "R→S Flip Zone", "R→S Flip Touches",
        "MA20 Slope 5D", "MACD Phase", "RSI14",
        "Volume Build Ratio", "Up/Down Volume Ratio", "OBV Trend",
        "Stock vs SPY 20D", "Sector vs SPY 20D", "Stock vs Sector 20D",
        "RS Acceleration", "Positive Catalyst", "Negative Catalyst",
        "ROE", "Operating Margin", "Debt to Equity", "Forward PE", "PEG", "Revenue Growth", "Earnings Growth",
        "CMS Context"
    ]
    display_cols = [c for c in display_cols if c in top_df.columns]

    fmt = {
        "Price": "{:.2f}",
        "Short-term Breakout": "{:.2f}",
        "MA20 Slope 5D": "{:.2%}",
        "RSI14": "{:.1f}",
        "Volume Build Ratio": "{:.2f}",
        "Up/Down Volume Ratio": "{:.2f}",
        "Stock vs SPY 20D": "{:+.1%}",
        "Sector vs SPY 20D": "{:+.1%}",
        "Stock vs Sector 20D": "{:+.1%}",
        "ROE": "{:.1%}",
        "Operating Margin": "{:.1%}",
        "Debt to Equity": "{:.1f}",
        "Forward PE": "{:.1f}",
        "PEG": "{:.2f}",
        "Revenue Growth": "{:.1%}",
        "Earnings Growth": "{:.1%}",
    }

    st.subheader("🌱 Early Engine V2 — 次日重点候选")
    cn_titles = {
        "Rank":"排名", "Ticker":"股票代码", "Company":"公司", "Early V2 Score":"Early V2总分",
        "Confidence":"信心等级", "Fundamental Confirmation":"基本面确认", "Fundamental Reason":"基本面依据",
        "Quality Fundamental":"质量", "FCF Fundamental":"现金流", "Debt Fundamental":"负债",
        "Valuation Fundamental":"估值", "Growth Fundamental":"增长",
        "Structure Score":"市场结构分", "Trend & Momentum Score":"趋势动量分",
        "Accumulation Score":"资金积累分", "Leadership Score":"相对强势分", "Catalyst Score":"催化剂分",
        "Price":"当前价格", "Major Resistance Zone":"主要压力区", "Resistance Touches":"压力测试次数",
        "Major Support Zone":"主要支撑区", "Short-term Breakout":"20日突破参考",
        "R→S Flip Zone":"R→S回踩区", "R→S Flip Touches":"R→S历史测试次数",
        "MA20 Slope 5D":"MA20 5日斜率", "MACD Phase":"MACD阶段", "Volume Build Ratio":"量能增强比",
        "Up/Down Volume Ratio":"涨跌量比", "OBV Trend":"OBV趋势",
        "Stock vs SPY 20D":"个股 vs SPY", "Sector vs SPY 20D":"板块 vs SPY",
        "Stock vs Sector 20D":"个股 vs 板块", "RS Acceleration":"RS加速度",
        "Catalyst Label":"催化剂状态", "Positive Catalyst":"正面催化剂", "Negative Catalyst":"负面催化剂",
        "ROE":"ROE", "Operating Margin":"营业利润率", "Debt to Equity":"Debt/Equity",
        "Forward PE":"Forward P/E", "PEG":"PEG", "Revenue Growth":"营收增长", "Earnings Growth":"盈利增长",
        "CMS Context":"CMS参考"
    }
    show_df = top_df[display_cols].rename(columns=cn_titles)
    fmt_cn = {cn_titles.get(k,k): v for k,v in fmt.items()}
    st.dataframe(
        show_df.style.format({k: v for k, v in fmt_cn.items() if k in show_df.columns}, na_rep=""),
        hide_index=True,
        use_container_width=True,
    )

    st.caption(
        "注意：这里的‘一级/二级重点候选’表示第二天重点监控，不代表开盘立即买入。"
        "真正买点将在 V4.3B 用1H和15min确认；买入后也由B继续管理。"
    )

    c1, c2 = st.columns(2)
    with c1:
        csv = reorder_a_columns(top_df).rename(columns=A_SHEET_CN_MAP).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "💾 下载 V4.3A Top 候选",
            csv,
            file_name=f"V43A_Daily_Top_{len(top_df)}_{datetime.now().strftime('%Y-%m-%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        if st.button("☁️ 保存到 Google Sheet", use_container_width=True):
            try:
                n, u = save_daily_candidates(top_df)
                st.success(f"已保存：新增 {n} 行，更新 {u} 行。工作表：{DAILY_WORKSHEET}")
            except Exception as e:
                st.error(f"Google Sheet 保存失败：{e}")

    with st.expander("查看五大模块详细解释"):
        st.markdown(
            """
**① 市场结构（25）**：一年日K Swing High/Low 聚类形成真正的压力/支撑区；同时保留20日短期突破位、Compression 和 R→S Flip。  
**② 趋势动量（20）**：MA20 5日斜率不再只看 >0；MACD区分零轴下转强、零轴下金叉、零轴上扩大、零轴上缩短；RSI只做健康度确认。  
**③ 资金积累（20）**：Volume Build + Up/Down Volume + OBV。日K只能判断‘资金积累证据’，不能宣称真实主动买盘。  
**④ 领导力（20）**：Stock vs SPY、Sector vs SPY、Stock vs Sector；5D只判断近期是否加速，不继续增加更多基准。  
**⑤ Catalyst（15）**：扩大正面/负面关键词并按事件类别识别；没有Catalyst不会直接淘汰，但明显负面Catalyst会压低候选级别。  
**⑥ Fundamental Confirmation（不计入100分）**：Quality / FCF / Debt / Valuation / Growth 只用于确认公司质量与 Confidence，不改变 Early V2 技术排名；数据缺失显示“数据不足”，不会自动判为失败。  
"""
        )

    with st.expander("查看未通过 Hard Filter 的股票"):
        failed = all_df[all_df["Hard Filter"] != "通过"].copy()
        if failed.empty:
            st.write("全部股票都通过 Hard Filter。")
        else:
            st.dataframe(
                failed[["Ticker", "Price", "Early V2 Score", "Hard Filter Reason"]]
                .sort_values("Early V2 Score", ascending=False),
                hide_index=True,
                use_container_width=True,
            )


if "v43a_top_df" in st.session_state and "v43a_all_df" in st.session_state:
    render_results(st.session_state["v43a_top_df"], st.session_state["v43a_all_df"])
else:
    st.caption("点击上方按钮开始第一次 V4.3A 扫描。V4.2.1 原版本不受影响。")

st.divider()
st.header("🔥 A强股回测 — 全扫描池 → 排名 → Top10")
st.caption("LIVE A选股逻辑完全不变。本模块只验证：约100只扫描池里后来真正上涨≥5%/≥8%的股票，当天被A排在第几名。")
if "a_all_history_save_msg" in st.session_state:
    st.info(st.session_state["a_all_history_save_msg"])
if st.button("🧪 运行 A 强股回测", use_container_width=True):
    try:
        hist=load_all_scan_history()
        if hist.empty:
            st.warning("A_AllScannedHistory 还没有历史。请先正常运行一次A扫描；新版会自动保存约100只的完整扫描结果。")
        else:
            with st.spinner("正在读取历史扫描池并计算未来1/3/5个交易日表现……"):
                bt=evaluate_scan_history(hist)
            st.session_state["a_strong_bt"] = bt
    except Exception as e:
        st.error(f"A强股回测失败：{e}")
if "a_strong_bt" in st.session_state:
    render_strong_stock_backtest(st.session_state["a_strong_bt"])
