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
    page_title="CMS Stock Screener V4.3A.3B-FIX2 — Strong Stock Backtest",
    page_icon="📈",
    layout="wide",
)

st.title("📈 CMS Stock Screener V4.3A.3B-FIX2 — Strong Stock Backtest")
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
# A5 — LAUNCH RESONANCE (TEST ONLY; A/B vs formal A4)
# One indicator = one column. Final decision is only 买 / 不买.
# =========================================================
def calc_a5_resonance(df, row=None):
    """A5.1: remove weak crude breakout rule, add chart-pattern recognition."""
    row = row or {}
    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    open_ = pd.to_numeric(df["Open"], errors="coerce")

    if len(close.dropna()) < 80:
        return {}

    px = safe_num(close.iloc[-1])

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    hist = macd - sig
    macd_ok = bool(macd.iloc[-1] > sig.iloc[-1] and hist.iloc[-1] > 0 and hist.iloc[-1] >= hist.iloc[-2])

    # KDJ
    ll9 = low.rolling(9).min()
    hh9 = high.rolling(9).max()
    rsv = (close - ll9) / (hh9 - ll9).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    k0, d0, j0 = safe_num(k.iloc[-1]), safe_num(d.iloc[-1]), safe_num(j.iloc[-1])
    kdj_ok = bool(k0 > d0 and k0 >= 45 and j0 <= 110)

    # RSI
    rsi_s = calc_rsi(close, 14)
    rsi = safe_num(rsi_s.iloc[-1])
    rsi_prev = safe_num(rsi_s.iloc[-3])
    rsi_ok = bool(50 <= rsi <= 72 and rsi >= rsi_prev)

    # Price-volume
    avg20v = safe_num(volume.rolling(20).mean().iloc[-1])
    avg5v = safe_num(volume.rolling(5).mean().iloc[-1])
    rvol = safe_num(volume.iloc[-1] / avg20v) if avg20v > 0 else np.nan
    vbuild = safe_num(avg5v / avg20v) if avg20v > 0 else np.nan
    ret1 = safe_num(close.iloc[-1] / close.iloc[-2] - 1)
    ret = close.pct_change()
    up_vol = volume.where(ret > 0, 0).tail(10).sum()
    dn_vol = volume.where(ret < 0, 0).tail(10).sum()
    udv = safe_num(up_vol / dn_vol) if dn_vol > 0 else np.nan
    pv_ok = bool(((ret1 > 0) and (rvol >= 1.10)) or ((vbuild >= 1.05) and (not pd.isna(udv)) and (udv >= 1.10)))

    # Relative strength
    rs_acc = safe_num(row.get("RS Acceleration", np.nan))
    rs_spy = safe_num(row.get("Stock vs SPY 20D", np.nan))
    rs_sector = safe_num(row.get("Stock vs Sector 20D", np.nan))
    if not pd.isna(rs_acc) and abs(rs_acc) > 2: rs_acc /= 100.0
    if not pd.isna(rs_spy) and abs(rs_spy) > 2: rs_spy /= 100.0
    if not pd.isna(rs_sector) and abs(rs_sector) > 2: rs_sector /= 100.0
    rs_ok = bool(
        (not pd.isna(rs_spy)) and rs_spy > 0 and
        (((not pd.isna(rs_acc)) and rs_acc > 0) or ((not pd.isna(rs_sector)) and rs_sector > 0))
    )

    # Chart pattern 1: platform compression
    h10, l10 = safe_num(high.tail(10).max()), safe_num(low.tail(10).min())
    h20, l20 = safe_num(high.tail(20).max()), safe_num(low.tail(20).min())
    range10 = (h10 / l10 - 1) if l10 > 0 else np.nan
    range20 = (h20 / l20 - 1) if l20 > 0 else np.nan
    near_top10 = (px / h10) if h10 > 0 else np.nan
    vol20m = safe_num(volume.tail(20).mean())
    vol_contract = safe_num(volume.tail(5).mean() / vol20m) if vol20m > 0 else np.nan
    platform_ok = bool(
        not pd.isna(range10) and not pd.isna(range20)
        and range10 <= 0.10 and range20 >= range10 * 1.20
        and near_top10 >= 0.97 and vol_contract <= 1.05
    )

    # Chart pattern 2: pullback then relaunch
    ma20 = close.rolling(20).mean()
    ma20_now = safe_num(ma20.iloc[-1])
    prior10_high = safe_num(high.shift(1).rolling(10).max().iloc[-1])
    prior_strength = bool(prior10_high > 0 and close.iloc[-6:-1].max() >= prior10_high * 0.98)
    touched_ma20 = bool(
        ma20_now > 0
        and low.iloc[-5:-1].min() <= ma20.iloc[-5:-1].max() * 1.02
        and low.iloc[-5:-1].min() >= ma20.iloc[-5:-1].min() * 0.94
    )
    pullback_vol = safe_num(volume.iloc[-5:-1].mean())
    prior_vol = safe_num(volume.iloc[-10:-5].mean())
    lighter_pullback = bool(prior_vol > 0 and pullback_vol / prior_vol <= 0.95)
    relaunch = bool(px > ma20_now and ret1 > 0 and ((rvol >= 1.05) or (hist.iloc[-1] > hist.iloc[-2])))
    pullback_relaunch_ok = bool(prior_strength and touched_ma20 and lighter_pullback and relaunch)

    # Chart pattern 3: higher high + higher low
    prev_high = safe_num(high.iloc[-15:-10].max())
    recent_high = safe_num(high.iloc[-10:-5].max())
    prev_low = safe_num(low.iloc[-15:-10].min())
    recent_low = safe_num(low.iloc[-10:-5].min())
    hhhl_ok = bool(prev_high > 0 and prev_low > 0 and recent_high > prev_high and recent_low > prev_low and px >= recent_low)

    # Chart pattern 4: volatility contraction
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr5 = safe_num(tr.rolling(5).mean().iloc[-1])
    atr20 = safe_num(tr.rolling(20).mean().iloc[-1])
    contraction_ok = bool(atr20 > 0 and atr5 / atr20 <= 0.82 and px > ma20_now)

    # Reject obvious false breakout / exhaustion
    body_top = max(safe_num(open_.iloc[-1]), px)
    candle_range = safe_num(high.iloc[-1] - low.iloc[-1])
    upper_shadow = safe_num(high.iloc[-1] - body_top)
    upper_shadow_ratio = upper_shadow / candle_range if candle_range > 0 else 0
    ext_ma20 = (px / ma20_now - 1) if ma20_now > 0 else np.nan
    false_breakout = bool(
        (upper_shadow_ratio >= 0.45 and px < high.iloc[-1] * 0.985)
        or ((not pd.isna(ext_ma20)) and ext_ma20 > 0.12)
    )

    pattern_count = int(sum([platform_ok, pullback_relaunch_ok, hhhl_ok, contraction_ok]))
    pattern_ok = bool(pattern_count >= 2 and not false_breakout)

    pattern_names = []
    if platform_ok: pattern_names.append("平台收缩")
    if pullback_relaunch_ok: pattern_names.append("缩量回踩再启动")
    if hhhl_ok: pattern_names.append("高低点抬升")
    if contraction_ok: pattern_names.append("波动收缩")

    if false_breakout:
        pattern_label = "假突破/过度延伸"
    elif pattern_names:
        pattern_label = "+".join(pattern_names)
    else:
        pattern_label = "无明显启动形态"

    flags = [macd_ok, kdj_ok, rsi_ok, pv_ok, rs_ok, pattern_ok]
    resonance_n = int(sum(flags))
    momentum_ok = bool(macd_ok or (kdj_ok and rsi_ok))
    decision = "买" if (resonance_n >= 4 and (pv_ok or pattern_ok) and momentum_ok and not false_breakout) else "不买"

    return {
        "A5决策": decision,
        "共振数": resonance_n,
        "图形共振": "是" if pattern_ok else "否",
        "图形形态": pattern_label,
        "假突破": "是" if false_breakout else "否",
        "MACD共振": "是" if macd_ok else "否",
        "KDJ共振": "是" if kdj_ok else "否",
        "RSI共振": "是" if rsi_ok else "否",
        "量价共振": "是" if pv_ok else "否",
        "RS共振": "是" if rs_ok else "否",
        "KDJ_K": k0, "KDJ_D": d0, "KDJ_J": j0,
        "当日RVOL_A5": rvol,
        "UpDownVol_A5": udv,
        "图形数": pattern_count,
    }

# =========================================================
# MODULE 3 — ACCUMULATION (MAX 20)
# =========================================================

def calc_a52_tvs_decision(r):
    """Experimental CMS A5.2: 图 + 量 + 势. Does not replace formal A4."""
    vol_ok = str(r.get("量价共振", "否")) == "是"
    rs_ok = str(r.get("RS共振", "否")) == "是"
    macd_ok = str(r.get("MACD共振", "否")) == "是"
    kdj_ok = str(r.get("KDJ共振", "否")) == "是"
    rsi_ok = str(r.get("RSI共振", "否")) == "是"
    momentum_n = int(macd_ok) + int(kdj_ok) + int(rsi_ok)

    price = pd.to_numeric(pd.Series([r.get("Price")]), errors="coerce").iloc[0]
    ma20 = pd.to_numeric(pd.Series([r.get("MA20")]), errors="coerce").iloc[0]
    ma50 = pd.to_numeric(pd.Series([r.get("MA50")]), errors="coerce").iloc[0]
    slope = pd.to_numeric(pd.Series([r.get("MA20 Slope 5D")]), errors="coerce").iloc[0]

    # 图：先判断大结构/位置，避免把暴跌后的局部Higher Low当成好图。
    chart_ok = bool(
        pd.notna(price) and pd.notna(ma20) and pd.notna(ma50) and pd.notna(slope)
        and price >= ma20
        and ma20 >= ma50 * 0.985
        and slope >= 0.002
        and price <= ma20 * 1.12
    )

    # 势：RS必须支持；MACD/KDJ/RSI至少一个确认。
    force_ok = bool(rs_ok and momentum_n >= 1)

    # 图、量、势三者缺一不可。
    buy = bool(chart_ok and vol_ok and force_ok)

    return pd.Series({
        "A5.2结果": "买" if buy else "不买",
        "图": "是" if chart_ok else "否",
        "量": "是" if vol_ok else "否",
        "势": "是" if force_ok else "否",
        "动量确认数": momentum_n
    })


def apply_a52_columns(df):
    if df is None or df.empty:
        return df
    out = df.copy()
    vals = out.apply(calc_a52_tvs_decision, axis=1)
    for c in vals.columns:
        out[c] = vals[c]
    return out


def render_a52_ab_comparison(bt):
    if bt is None or bt.empty or "5D Max Gain" not in bt.columns:
        return
    d = apply_a52_columns(bt)
    d["5D Max Gain"] = pd.to_numeric(d["5D Max Gain"], errors="coerce")
    d = d.dropna(subset=["5D Max Gain"])

    a52 = d[d["A5.2结果"].eq("买")].copy()

    def _stats(name, x):
        if x.empty:
            return {"模型":name,"样本数":0,"≥3%":None,"≥5%":None,"≥8%":None,
                    "平均5D最大涨幅":None,"中位5D最大涨幅":None,"弱<2%":None}
        g=x["5D Max Gain"]
        return {"模型":name,"样本数":len(x),"≥3%":(g>=.03).mean(),"≥5%":(g>=.05).mean(),
                "≥8%":(g>=.08).mean(),"平均5D最大涨幅":g.mean(),
                "中位5D最大涨幅":g.median(),"弱<2%":(g<.02).mean()}

    rows = [_stats("A5.2 图+量+势", a52)]
    comp = pd.DataFrame(rows)

    st.header("🧪 A5.2 图·量·势 A/B Test")
    st.caption("实验规则：图形位置健康 + 量价确认 + RS确认 + MACD/KDJ/RSI至少1个确认。正式A4和B/C均未修改。")
    st.caption("目标基准（旧A5 60日）：≥5% 41.3%｜≥8% 19.8%｜平均5D最大涨幅 5.67%｜弱<2% 25.4%。")
    st.dataframe(
        comp.style.format({
            "≥3%":"{:.1%}","≥5%":"{:.1%}","≥8%":"{:.1%}",
            "平均5D最大涨幅":"{:+.2%}","中位5D最大涨幅":"{:+.2%}","弱<2%":"{:.1%}"
        }, na_rep="—"),
        use_container_width=True, hide_index=True
    )

    if not a52.empty:
        st.subheader("A5.2 买入案例")
        cols=[c for c in ["A5.2结果","Ticker","Replay Date","Price","图","量","势",
                          "量价共振","RS共振","MACD共振","KDJ共振","RSI共振",
                          "5D Max Gain","5D Close Return","5D Max Drawdown"] if c in a52.columns]
        st.dataframe(a52[cols].head(300), use_container_width=True, hide_index=True)


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
    # V4.3A.4 正式规则：MA200 不再作为一票否决。
    # MA200 仍保留在趋势/诊断字段中，但价格低于 MA200 不再自动淘汰。
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
        row.update(calc_a5_resonance(df, row))
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
    """Save Top candidates with ONE batch write instead of row-by-row API calls."""
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
    headers = list(sheet_df.columns)

    existing = ws.get_all_values()
    if existing and existing[0] != headers:
        # Schema changed: rebuild once. This costs two writes only on version changes.
        ws.clear()
        existing = []

    date_col, ticker_col = "扫描日期", "股票代码"
    date_idx, ticker_idx = headers.index(date_col), headers.index(ticker_col)

    old_rows = existing[1:] if existing else []
    new_map = {
        (str(r[date_col]), str(r[ticker_col]).upper()): [_cell(r.get(c, "")) for c in headers]
        for _, r in sheet_df.iterrows()
    }

    merged_rows = []
    seen = set()
    updated_rows = 0
    for row in old_rows:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        padded = padded[:len(headers)]
        key = (str(padded[date_idx]), str(padded[ticker_idx]).upper())
        if key in new_map:
            merged_rows.append(new_map[key])
            seen.add(key)
            updated_rows += 1
        else:
            merged_rows.append(padded)

    for key, vals in new_map.items():
        if key not in seen:
            merged_rows.append(vals)

    new_rows = len(new_map) - updated_rows
    # One matrix update = one Sheets write request in normal operation.
    ws.update("A1", [headers] + merged_rows, value_input_option="USER_ENTERED")
    return new_rows, updated_rows



# =========================================================
# A STRONG-STOCK HISTORY / BACKTEST — V4.3A.3B-FIX2
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
    """Save the whole scanned universe with ONE batch write per scan.

    This avoids Google Sheets' per-user per-minute write quota, which the old
    row-by-row append/update loop could hit when ~100 stocks were saved.
    """
    ws = get_named_worksheet(ALL_SCAN_WORKSHEET)
    d = all_df.copy()
    d.insert(0, "Scan Date", datetime.now().strftime("%Y-%m-%d"))
    d.insert(1, "Scan Time", datetime.now().strftime("%H:%M:%S"))

    # Rank the whole universe with exactly the same LIVE ordering logic.
    qorder = {"✅ 通过":0, "⚠️ 观察":1, "❌ 不适合Early":2}
    d["_q"] = d["质量检查"].map(qorder).fillna(9)
    d = d.sort_values(
        ["_q","Early V2 Score","Structure Score","Leadership Score","Accumulation Score"],
        ascending=[True,False,False,False,False]
    ).drop(columns="_q").reset_index(drop=True)
    d["Universe Rank"] = d.index + 1

    keep = ["Scan Date","Scan Time","Ticker","Company","Sector","Universe Rank","Hard Filter","Hard Filter Reason",
            "质量检查","结构阶段","Early V2 Score","Structure Score","Trend & Momentum Score","Accumulation Score",
            "Leadership Score","Catalyst Score","Catalyst Label","Price","ATR14","RVOL","Dollar Volume",
            "MA20 Slope 5D","MACD Phase","RSI14","Volume Build Ratio","Up/Down Volume Ratio",
            "Stock vs SPY 20D","Sector vs SPY 20D","Stock vs Sector 20D","RS Acceleration","Confidence",
            "Fundamental Confirmation"]
    d = d[[c for c in keep if c in d.columns]].copy()
    headers = list(d.columns)

    existing = ws.get_all_values()
    if existing and existing[0] != headers:
        # Diagnostic sheet only: rebuild automatically on schema changes.
        ws.clear()
        existing = []

    di, ti = headers.index("Scan Date"), headers.index("Ticker")
    old_rows = existing[1:] if existing else []

    new_map = {
        (str(r["Scan Date"]), str(r["Ticker"]).upper()): [_cell(r.get(c, "")) for c in headers]
        for _, r in d.iterrows()
    }

    merged_rows = []
    seen = set()
    upd = 0
    for row in old_rows:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        padded = padded[:len(headers)]
        key = (str(padded[di]), str(padded[ti]).upper())
        if key in new_map:
            merged_rows.append(new_map[key])
            seen.add(key)
            upd += 1
        else:
            merged_rows.append(padded)

    for key, vals in new_map.items():
        if key not in seen:
            merged_rows.append(vals)

    new = len(new_map) - upd
    # One bulk matrix update instead of ~100 append/update requests.
    ws.update("A1", [headers] + merged_rows, value_input_option="USER_ENTERED")
    return new, upd

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
# HISTORICAL A REPLAY — V4.3A.3C
# Re-runs the historical-price-reconstructable A core on old dates.
# IMPORTANT: Yahoo's current news feed cannot reconstruct historical Catalyst
# point-in-time without look-ahead, so Catalyst is EXCLUDED from replay ranking.
# Fundamental Confirmation never entered the 100-point Early V2 score, so it is
# also not needed for replay ranking.  The replay core is therefore 85 points:
# Structure 25 + Trend 20 + Accumulation 20 + Leadership 20.
# =========================================================

def _norm_daily_index(df):
    d = df.copy()
    idx = pd.to_datetime(d.index)
    try:
        if idx.tz is not None:
            idx = idx.tz_localize(None)
    except Exception:
        pass
    d.index = idx
    return d.sort_index()


def _historical_benchmark_snapshot(benchmark_data, asof_date):
    out = {}
    asof = pd.Timestamp(asof_date)
    for t, df in benchmark_data.items():
        if df is None or df.empty:
            continue
        d = _norm_daily_index(df)
        d = d[d.index <= asof]
        if d.empty:
            continue
        c = pd.to_numeric(d['Close'], errors='coerce').dropna()
        if len(c) < 22:
            continue
        out[t] = {'5D': pct_return(c, 5), '20D': pct_return(c, 20)}
    return out


def _get_replay_sector_map(tickers):
    """Prefer sectors already obtained by the LIVE scan; otherwise use cached Yahoo info."""
    sector_map = {}
    live = st.session_state.get('v43a_all_df')
    if isinstance(live, pd.DataFrame) and not live.empty and {'Ticker','Sector'}.issubset(live.columns):
        sector_map.update({
            str(r['Ticker']).upper(): str(r['Sector'])
            for _, r in live[['Ticker','Sector']].dropna().iterrows()
        })
    missing = [t for t in tickers if t not in sector_map]
    if missing:
        for t in missing:
            try:
                _, sec, _ = get_company_info(t)
                sector_map[t] = sec
            except Exception:
                sector_map[t] = 'Unknown'
    return sector_map


def analyze_historical_a_core(ticker, df_hist, sector, benchmarks):
    """Historical replay of A components that can be reconstructed without future data."""
    try:
        if df_hist is None or len(df_hist) < 210:
            return None
        df = _norm_daily_index(df_hist)
        for c in ['Open','High','Low','Close','Volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['High','Low','Close','Volume'])
        if len(df) < 210:
            return None

        close, high, low, volume = df['Close'], df['High'], df['Low'], df['Volume']
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
        m4 = score_leadership(ret5, ret20, sector, benchmarks)

        replay85 = int(m1['score'] + m2['score'] + m3['score'] + m4['score'])
        replay100 = float(replay85 / 85.0 * 100.0)

        row = {
            'Ticker': ticker,
            'Sector': sector,
            'Price': price,
            'ATR14': atr14,
            'RVOL': rvol,
            'Dollar Volume': dollar_volume,
            '5D Return': ret5,
            '20D Return': ret20,
            'Structure Score': m1['score'],
            'Trend & Momentum Score': m2['score'],
            'Accumulation Score': m3['score'],
            'Leadership Score': m4['score'],
            'Replay Core Score 85': replay85,
            'Replay Core Score 100': replay100,
            'Catalyst Score': np.nan,
            'Catalyst Label': '历史回放未使用',
            'Major Resistance Zone': m1['Major Resistance Zone'],
            'Major Support Zone': m1['Major Support Zone'],
            'Short-term Breakout': m1['Short-term Breakout'],
            'Distance to Major Resistance': m1['Distance to Major Resistance'],
            'Distance to Short Breakout': m1['Distance to Short Breakout'],
            'Compression Ratio': m1['Compression Ratio'],
            'R→S Flip': m1['R→S Flip'],
            'R→S Flip Zone': m1['R→S Flip Zone'],
            'R→S Flip Touches': m1['R→S Flip Touches'],
            'MA20': m2['MA20'], 'MA50': m2['MA50'], 'MA200': m2['MA200'],
            'MA20 Slope 5D': m2['MA20 Slope 5D'],
            'MACD Phase': m2['MACD Phase'], 'RSI14': m2['RSI14'],
            'Volume Build Ratio': m3['Volume Build Ratio'],
            'Up/Down Volume Ratio': m3['Up/Down Volume Ratio'],
            'OBV Trend': m3['OBV Trend'],
            'Stock vs SPY 20D': m4['Stock vs SPY 20D'],
            'Sector vs SPY 20D': m4['Sector vs SPY 20D'],
            'Stock vs Sector 20D': m4['Stock vs Sector 20D'],
            'RS Acceleration': m4['RS Acceleration'],
        }

        row.update(calc_a5_resonance(df, row))

        hard_ok, hard_reason = passes_v43a_hard_filter(row)
        row['Hard Filter'] = '通过' if hard_ok else '未通过'
        row['Hard Filter Reason'] = hard_reason

        stage, stage_quality, stage_reason = classify_structure_stage(row, structure_raw, atr14)
        row['结构阶段'] = stage
        row['结构质量'] = stage_quality
        row['结构依据'] = stage_reason
        q, qr = quality_gate(row)
        row['质量检查'] = q
        row['质量原因'] = qr
        return row
    except Exception:
        return None


def _future_5d_labels(full_df, asof_date, base_close):
    d = _norm_daily_index(full_df)
    future = d[d.index > pd.Timestamp(asof_date)].head(5)
    if len(future) < 5 or base_close <= 0:
        return None
    hi = pd.to_numeric(future['High'], errors='coerce')
    lo = pd.to_numeric(future['Low'], errors='coerce')
    cl = pd.to_numeric(future['Close'], errors='coerce')
    return {
        '1D Max Gain': float(hi.iloc[:1].max() / base_close - 1),
        '3D Max Gain': float(hi.iloc[:3].max() / base_close - 1),
        '5D Max Gain': float(hi.iloc[:5].max() / base_close - 1),
        '5D Close Return': float(cl.iloc[4] / base_close - 1),
        '5D Max Drawdown': float(lo.iloc[:5].min() / base_close - 1),
    }



def _historical_hard_filter_variant(r, relax_ma20=False, relax_ma200=False):
    """Historical A/B test only. LIVE passes_v43a_hard_filter() is NOT changed."""
    if r is None:
        return False
    try:
        if r["Price"] < 5:
            return False
        if r["Dollar Volume"] < 20_000_000:
            return False
        if (not relax_ma20) and r["Price"] < r["MA20"] * 0.99:
            return False
        if r["Price"] < r["MA50"] * 0.97:
            return False
        if (not relax_ma200) and r["Price"] < r["MA200"] * 0.95:
            return False
        if pd.isna(r["MA20 Slope 5D"]) or r["MA20 Slope 5D"] < 0.002:
            return False
        if r["Structure Score"] < 8:
            return False
        return True
    except Exception:
        return False


def _assign_variant_rank(day, rank_cols, ok_col, rank_col):
    eligible = day[day[ok_col]].copy()
    eligible = eligible.sort_values(
        rank_cols, ascending=[True, False, False, False, False]
    ).reset_index(drop=True)
    eligible[rank_col] = eligible.index + 1
    rank_map = dict(zip(eligible["Ticker"], eligible[rank_col]))
    day[rank_col] = day["Ticker"].map(rank_map)
    return day


def run_historical_a_replay(replay_days=30, progress_bar=None, status_box=None):
    """Replay the historical A core across the entire current universe.

    The final 5 trading days are reserved for forward outcome labels, so every
    replayed date has a complete 5-day future window available immediately.
    """
    tickers = get_universe()
    all_tickers = tuple(dict.fromkeys(tickers + BENCHMARK_TICKERS))
    if status_box is not None:
        status_box.write('正在下载约2年历史日K（股票池 + SPY/板块ETF）……')
    data_all = safe_batch_download(all_tickers, '2y')
    stock_data = {t: _norm_daily_index(data_all[t]) for t in tickers if t in data_all and data_all[t] is not None and not data_all[t].empty}
    bench_data = {t: _norm_daily_index(data_all[t]) for t in BENCHMARK_TICKERS if t in data_all and data_all[t] is not None and not data_all[t].empty}

    spy = bench_data.get('SPY')
    if spy is None or spy.empty:
        raise RuntimeError('历史回放无法取得 SPY 日K。')
    spy_dates = list(spy.index)
    if len(spy_dates) < 220 + replay_days + 5:
        raise RuntimeError('历史数据不足，无法完成所选回放天数。')

    # Mature historical dates only: exclude the latest 5 trading days.
    mature_dates = spy_dates[:-5]
    replay_dates = mature_dates[-int(replay_days):]
    sector_map = _get_replay_sector_map(tickers)

    all_out = []
    total_steps = max(1, len(replay_dates) * len(tickers))
    done = 0

    for di, asof in enumerate(replay_dates, start=1):
        if status_box is not None:
            status_box.write(f'历史回放 {pd.Timestamp(asof).date()}（{di}/{len(replay_dates)}）— 正在扫描约{len(tickers)}只……')
        benchmarks = _historical_benchmark_snapshot(bench_data, asof)
        day_rows = []
        for t in tickers:
            full = stock_data.get(t)
            done += 1
            if progress_bar is not None:
                progress_bar.progress(min(100, int(done / total_steps * 100)))
            if full is None or full.empty:
                continue
            hist = full[full.index <= pd.Timestamp(asof)]
            row = analyze_historical_a_core(t, hist, sector_map.get(t, 'Unknown'), benchmarks)
            if row is None:
                continue
            row['Replay Date'] = pd.Timestamp(asof).strftime('%Y-%m-%d')
            day_rows.append(row)

        if not day_rows:
            continue
        day = pd.DataFrame(day_rows)

        # Whole-pool rank for diagnostics.
        qorder = {'✅ 通过':0, '⚠️ 观察':1, '❌ 不适合Early':2}
        day['_q'] = day['质量检查'].map(qorder).fillna(9)
        rank_cols = ['_q','Replay Core Score 85','Structure Score','Leadership Score','Accumulation Score']
        day = day.sort_values(rank_cols, ascending=[True,False,False,False,False]).reset_index(drop=True)
        day['Replay Universe Rank'] = day.index + 1

        # ---------------------------------------------------------
        # SAME-DATE 3-WAY HARD FILTER TEST
        # Control: original A3
        # MA200-only: relax MA200 only
        # Combined: relax MA20 + MA200
        # LIVE A logic is NOT changed.
        # ---------------------------------------------------------
        day['HF Control'] = day.apply(
            lambda r: _historical_hard_filter_variant(r, False, False), axis=1
        )
        day['HF MA200-only'] = day.apply(
            lambda r: _historical_hard_filter_variant(r, False, True), axis=1
        )
        day['HF Combined'] = day.apply(
            lambda r: _historical_hard_filter_variant(r, True, True), axis=1
        )

        day = _assign_variant_rank(day, rank_cols, 'HF Control', 'Rank Control')
        day = _assign_variant_rank(day, rank_cols, 'HF MA200-only', 'Rank MA200-only')
        day = _assign_variant_rank(day, rank_cols, 'HF Combined', 'Rank Combined')

        # Backward-compatible aliases: existing diagnostic tables continue to show Control A3.
        day['Replay Eligible Rank'] = day['Rank Control']
        day['Replay Top10'] = day['Rank Control'].apply(
            lambda x: bool(pd.notna(x) and float(x) <= 10)
        )

        # Add future labels only AFTER ranking.
        for _, r in day.iterrows():
            rec = dict(r)
            full = stock_data.get(str(r['Ticker']).upper())
            labels = _future_5d_labels(full, asof, float(r['Price'])) if full is not None else None
            if labels is not None:
                rec.update(labels)
                g = labels['5D Max Gain']
                rec['Hit +3%'] = bool(g >= 0.03)
                rec['Hit +5%'] = bool(g >= 0.05)
                rec['Hit +8%'] = bool(g >= 0.08)
                rec['Strength Class'] = '🚀 ≥8%' if g >= .08 else ('🔥 5–8%' if g >= .05 else ('🟡 2–5%' if g >= .02 else '⚪ <2%'))
                all_out.append(rec)

    out = pd.DataFrame(all_out)
    if progress_bar is not None:
        progress_bar.progress(100)
    if status_box is not None:
        status_box.empty()
    return out




def hard_filter_rule_failures(r):
    """Return every failed hard-filter rule, not just the first one. Diagnostic only."""
    fails = []
    try:
        if pd.isna(r.get('Price')) or r.get('Price', 0) < 5:
            fails.append('股价低于$5')
        if pd.isna(r.get('Dollar Volume')) or r.get('Dollar Volume', 0) < 20_000_000:
            fails.append('流动性不足')
        if pd.isna(r.get('MA20')) or r.get('Price', np.nan) < r.get('MA20', np.nan) * 0.99:
            fails.append('价格明显低于MA20')
        if pd.isna(r.get('MA50')) or r.get('Price', np.nan) < r.get('MA50', np.nan) * 0.97:
            fails.append('价格明显低于MA50')
        if pd.isna(r.get('MA200')) or r.get('Price', np.nan) < r.get('MA200', np.nan) * 0.95:
            fails.append('价格明显低于MA200')
        if pd.isna(r.get('MA20 Slope 5D')) or r.get('MA20 Slope 5D', np.nan) < 0.002:
            fails.append('MA20斜率不足0.2%')
        if pd.isna(r.get('Structure Score')) or r.get('Structure Score', 0) < 8:
            fails.append('市场结构不足')
    except Exception:
        return ['数据不足']
    return fails


def add_hard_filter_diagnostic_columns(bt):
    if bt is None or bt.empty:
        return bt
    x = bt.copy()
    all_fails = x.apply(lambda r: hard_filter_rule_failures(r), axis=1)
    x['Hard Filter All Failures'] = all_fails.apply(lambda z: '；'.join(z) if z else '通过')
    x['Hard Filter Failure Count'] = all_fails.apply(len)
    return x


def render_hard_filter_diagnostics(d):
    st.subheader('🧪 Hard Filter 漏杀诊断')
    st.caption('只做历史诊断，不改变 LIVE A。每只股票可能同时违反多条规则，所以“失败规则次数”允许重复计数。')
    x = add_hard_filter_diagnostic_columns(d)
    rejected = x[x['Hard Filter'] != '通过'].copy()
    if rejected.empty:
        st.info('历史回放中没有被 Hard Filter 淘汰的样本。')
        return

    rules = ['股价低于$5','流动性不足','价格明显低于MA20','价格明显低于MA50','价格明显低于MA200','MA20斜率不足0.2%','市场结构不足']
    rows=[]
    strong5 = x['5D Max Gain'] >= .05
    strong8 = x['5D Max Gain'] >= .08
    weak = x['5D Max Gain'] < .02
    total_rej5 = int(((x['Hard Filter']!='通过') & strong5).sum())
    total_rej8 = int(((x['Hard Filter']!='通过') & strong8).sum())
    for rule in rules:
        failed = x['Hard Filter All Failures'].str.contains(rule, regex=False, na=False)
        n_all = int(failed.sum())
        n5 = int((failed & strong5).sum())
        n8 = int((failed & strong8).sum())
        nw = int((failed & weak).sum())
        rows.append({
            'Hard Filter规则':rule,
            '失败样本':n_all,
            '其中5日≥5%':n5,
            '占全部被漏≥5%强股': n5/total_rej5 if total_rej5 else np.nan,
            '其中5日≥8%':n8,
            '占全部被漏≥8%强股': n8/total_rej8 if total_rej8 else np.nan,
            '其中弱股<2%':nw,
            '强股/弱股比': n5/nw if nw else np.nan,
        })
    diag=pd.DataFrame(rows).sort_values(['其中5日≥5%','其中5日≥8%'],ascending=False)
    st.dataframe(diag.style.format({'占全部被漏≥5%强股':'{:.1%}','占全部被漏≥8%强股':'{:.1%}','强股/弱股比':'{:.2f}'},na_rep=''),hide_index=True,use_container_width=True)

    st.markdown('**如果只放宽一条规则：理论上能救回多少强股，同时会放进多少弱股**')
    # A sample is rescued by relaxing one rule only if it fails exactly that one rule.
    relax_rows=[]
    for rule in rules:
        only = (x['Hard Filter Failure Count']==1) & x['Hard Filter All Failures'].eq(rule)
        n= int(only.sum()); n5=int((only & strong5).sum()); n8=int((only & strong8).sum()); nw=int((only & weak).sum())
        relax_rows.append({
            '单独放宽规则':rule,'新增进入样本':n,'救回≥5%强股':n5,'救回≥8%强股':n8,'同时放入弱股<2%':nw,
            '≥5%强股占新增': n5/n if n else np.nan,
            '救回强股/弱股': n5/nw if nw else np.nan,
        })
    relax=pd.DataFrame(relax_rows).sort_values(['救回≥5%强股','救回≥8%强股'],ascending=False)
    st.dataframe(relax.style.format({'≥5%强股占新增':'{:.1%}','救回强股/弱股':'{:.2f}'},na_rep=''),hide_index=True,use_container_width=True)

    st.markdown('**被 Hard Filter 淘汰但后来 5日≥8% 的代表性强股**')
    examples=x[(x['Hard Filter']!='通过') & (x['5D Max Gain']>=.08)].copy().sort_values('5D Max Gain',ascending=False)
    cols=['Replay Date','Ticker','Replay Universe Rank','Hard Filter All Failures','Replay Core Score 85','Structure Score','Trend & Momentum Score','Accumulation Score','Leadership Score','MA20 Slope 5D','5D Max Gain','5D Close Return','5D Max Drawdown']
    ex=examples[[c for c in cols if c in examples.columns]].head(100)
    st.dataframe(ex.style.format({'MA20 Slope 5D':'{:.2%}','5D Max Gain':'{:+.2%}','5D Close Return':'{:+.2%}','5D Max Drawdown':'{:+.2%}'},na_rep=''),hide_index=True,use_container_width=True)



def render_3way_hardfilter_comparison(bt):
    """Direct same-window comparison of A3 Control vs MA200-only vs Combined.

    Robust to Streamlit hot-reload/session_state: if the cached replay was created by
    the previous app version and does not yet contain the new comparison columns,
    rebuild those columns directly from the cached historical rows instead of crashing.
    """
    if bt is None or bt.empty:
        return

    d = bt.copy()

    required_variant_cols = [
        'HF Control', 'HF MA200-only', 'HF Combined',
        'Rank Control', 'Rank MA200-only', 'Rank Combined'
    ]
    if not all(c in d.columns for c in required_variant_cols):
        # Rebuild the three Hard Filter variants from already-computed historical features.
        d['HF Control'] = d.apply(
            lambda r: _historical_hard_filter_variant(r, False, False), axis=1
        )
        d['HF MA200-only'] = d.apply(
            lambda r: _historical_hard_filter_variant(r, False, True), axis=1
        )
        d['HF Combined'] = d.apply(
            lambda r: _historical_hard_filter_variant(r, True, True), axis=1
        )

        qorder = {'✅ 通过':0, '⚠️ 观察':1, '❌ 不适合Early':2}
        d['_cmp_q'] = d.get('质量检查', pd.Series(index=d.index, dtype=object)).map(qorder).fillna(9)

        def _rank_one_group(g, ok_col, rank_col):
            gg = g[g[ok_col]].copy()
            gg = gg.sort_values(
                ['_cmp_q','Replay Core Score 85','Structure Score','Leadership Score','Accumulation Score'],
                ascending=[True,False,False,False,False]
            )
            rank_map = {idx: i+1 for i, idx in enumerate(gg.index)}
            return pd.Series([rank_map.get(idx, np.nan) for idx in g.index], index=g.index)

        for ok_col, rank_col in [
            ('HF Control','Rank Control'),
            ('HF MA200-only','Rank MA200-only'),
            ('HF Combined','Rank Combined')
        ]:
            d[rank_col] = np.nan
            for _, idxs in d.groupby('Replay Date').groups.items():
                g = d.loc[idxs]
                ranks = _rank_one_group(g, ok_col, rank_col)
                d.loc[ranks.index, rank_col] = ranks.values

        d = d.drop(columns=['_cmp_q'], errors='ignore')
        st.info('检测到旧版缓存的历史回测结果，已自动重建三版本排名；无需重新等待60日数据。')

    d['5D Max Gain'] = pd.to_numeric(d['5D Max Gain'], errors='coerce')
    d = d.dropna(subset=['5D Max Gain'])
    if d.empty:
        return

    versions = [
        ('A3 Control', 'HF Control', 'Rank Control'),
        ('MA200-only', 'HF MA200-only', 'Rank MA200-only'),
        ('MA20+MA200', 'HF Combined', 'Rank Combined'),
    ]

    st.header('🧪 60日同窗口三版本 A/B/C 对照')
    st.caption(
        '同一批历史日期、同一股票池、同一排名逻辑，只改变 Hard Filter。'
        'LIVE A 当前正式采用 MA200-only；本表保留 A3 / MA200-only / MA20+MA200 的历史对照。'
    )

    strong_all = d[d['5D Max Gain'] >= .05].copy()
    rows = []
    for label, hf_col, rank_col in versions:
        top10 = d[pd.to_numeric(d[rank_col], errors='coerce') <= 10].copy()
        gg = pd.to_numeric(top10['5D Max Gain'], errors='coerce').dropna()
        hf_pass = float(d[hf_col].mean()) if hf_col in d.columns else np.nan
        strong_hf_capture = (
            float(strong_all[hf_col].mean())
            if (not strong_all.empty and hf_col in strong_all.columns) else np.nan
        )
        strong_top20 = (
            float((pd.to_numeric(strong_all[rank_col], errors='coerce') <= 20).fillna(False).mean())
            if not strong_all.empty else np.nan
        )
        strong_top10 = (
            float((pd.to_numeric(strong_all[rank_col], errors='coerce') <= 10).fillna(False).mean())
            if not strong_all.empty else np.nan
        )

        rows.append({
            '版本': label,
            'Top10样本': len(gg),
            'Top10 ≥3%': (gg >= .03).mean() if len(gg) else np.nan,
            'Top10 ≥5%': (gg >= .05).mean() if len(gg) else np.nan,
            'Top10 ≥8%': (gg >= .08).mean() if len(gg) else np.nan,
            'Top10平均5日最大涨幅': gg.mean() if len(gg) else np.nan,
            'Top10中位数5日最大涨幅': gg.median() if len(gg) else np.nan,
            'Hard Filter通过率': hf_pass,
            '≥5%强股通过HF': strong_hf_capture,
            '≥5%强股进入Top20': strong_top20,
            '≥5%强股进入Top10': strong_top10,
        })

    comp = pd.DataFrame(rows)

    # Identify the best variant by the main strong-stock metrics.
    score_cols = ['Top10 ≥5%', 'Top10 ≥8%', 'Top10平均5日最大涨幅']
    comp['_wins'] = 0
    for c in score_cols:
        if comp[c].notna().any():
            best = comp[c].max()
            comp.loc[comp[c] == best, '_wins'] += 1
    best_row = comp.sort_values(
        ['_wins','Top10 ≥8%','Top10 ≥5%','Top10平均5日最大涨幅'],
        ascending=[False,False,False,False]
    ).iloc[0]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric('回放交易日', int(d['Replay Date'].nunique()))
    c2.metric('股票-日期样本', len(d))
    c3.metric('当前领先版本', str(best_row['版本']))
    c4.metric('领先版 Top10 ≥5%', f"{best_row['Top10 ≥5%']:.1%}")

    show = comp.drop(columns=['_wins'])
    st.dataframe(
        show.style.format({
            'Top10 ≥3%':'{:.1%}',
            'Top10 ≥5%':'{:.1%}',
            'Top10 ≥8%':'{:.1%}',
            'Top10平均5日最大涨幅':'{:+.2%}',
            'Top10中位数5日最大涨幅':'{:+.2%}',
            'Hard Filter通过率':'{:.1%}',
            '≥5%强股通过HF':'{:.1%}',
            '≥5%强股进入Top20':'{:.1%}',
            '≥5%强股进入Top10':'{:.1%}',
        }, na_rep=''),
        hide_index=True,
        use_container_width=True
    )

    # Direct deltas vs Control make the decision easier.
    control = comp[comp['版本']=='A3 Control'].iloc[0]
    delta_rows = []
    for _, r in comp[comp['版本']!='A3 Control'].iterrows():
        delta_rows.append({
            '测试版本': r['版本'],
            'Δ Top10 ≥3%': r['Top10 ≥3%'] - control['Top10 ≥3%'],
            'Δ Top10 ≥5%': r['Top10 ≥5%'] - control['Top10 ≥5%'],
            'Δ Top10 ≥8%': r['Top10 ≥8%'] - control['Top10 ≥8%'],
            'Δ 平均最大涨幅': r['Top10平均5日最大涨幅'] - control['Top10平均5日最大涨幅'],
            'Δ 强股进入Top10': r['≥5%强股进入Top10'] - control['≥5%强股进入Top10'],
        })
    st.markdown('**相对原 A3 的净变化**')
    delta = pd.DataFrame(delta_rows)
    st.dataframe(
        delta.style.format({
            'Δ Top10 ≥3%':'{:+.1%}',
            'Δ Top10 ≥5%':'{:+.1%}',
            'Δ Top10 ≥8%':'{:+.1%}',
            'Δ 平均最大涨幅':'{:+.2%}',
            'Δ 强股进入Top10':'{:+.1%}',
        }, na_rep=''),
        hide_index=True,
        use_container_width=True
    )




def render_a4_a5_resonance_comparison(bt):
    """Same-window A/B test: formal A4 ranking vs A5 resonance ranking."""
    if bt is None or bt.empty:
        return
    d = bt.copy()
    req = [
        'Replay Date','Ticker','Replay Eligible Rank','5D Max Gain',
        'A5决策','共振数',
        'MACD共振','KDJ共振','RSI共振','量价共振','RS共振','图形共振'
    ]
    missing = [c for c in req if c not in d.columns]
    if missing:
        st.warning(
            "当前 Session 里还是旧版本 Replay 缓存，缺少 A5.1 新字段："
            + "、".join(missing)
            + "。请点击上面的“🧪 运行 60日三版本同屏回测”重新跑一次。"
        )
        return

    d['5D Max Gain'] = pd.to_numeric(d['5D Max Gain'], errors='coerce')
    d['共振数'] = pd.to_numeric(d['共振数'], errors='coerce')
    d = d.dropna(subset=['5D Max Gain'])
    if d.empty:
        return

    # A4 = existing eligible Top10 per replay day.
    a4 = d[d['Replay Eligible Rank'] <= 10].copy()

    # A5 = among formal A4 hard-filter pass names, BUY first, then resonance count,
    # then existing core score as tie-breaker; take up to Top10 each day.
    pool = d[d['Hard Filter'].eq('通过')].copy()
    pool['_buy'] = (pool['A5决策'] == '买').astype(int)
    pool = pool.sort_values(
        ['Replay Date','_buy','共振数','Replay Core Score 85','Leadership Score','Accumulation Score'],
        ascending=[True,False,False,False,False,False]
    )
    a5 = pool.groupby('Replay Date', group_keys=False).head(10).copy()
    a5 = a5[a5['A5决策'] == '买'].copy()  # no forced 10 names

    def summary(x, label):
        g = pd.to_numeric(x['5D Max Gain'], errors='coerce').dropna()
        return {
            '版本': label,
            '入选样本': len(g),
            '≥3%': (g >= .03).mean() if len(g) else np.nan,
            '≥5%': (g >= .05).mean() if len(g) else np.nan,
            '≥8%': (g >= .08).mean() if len(g) else np.nan,
            '平均5日最大涨幅': g.mean() if len(g) else np.nan,
            '中位数5日最大涨幅': g.median() if len(g) else np.nan,
            '弱股<2%': (g < .02).mean() if len(g) else np.nan,
        }

    comp = pd.DataFrame([summary(a4,'当前A4 Top10'), summary(a5,'A5.1 图形共振买入')])
    st.header("🆚 当前A4 vs A5.1图形共振：谁更会找到未来大涨股")
    st.caption("同一历史日期、同一股票池、同一未来5日结果。A5.1不强制每天凑10只；只有满足“买”的股票才进入A5结果。")
    st.dataframe(
        comp.style.format({
            '≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
            '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
        }, na_rep=''),
        hide_index=True, use_container_width=True
    )

    # Indicator hit-rate table: one indicator per row, useful for deciding what to keep.
    rows = []
    for c in ['MACD共振','KDJ共振','RSI共振','量价共振','RS共振','图形共振']:
        yes = d[d[c] == '是']
        g = pd.to_numeric(yes['5D Max Gain'], errors='coerce').dropna()
        rows.append({
            '指标': c,
            '触发样本': len(g),
            '≥5%命中率': (g >= .05).mean() if len(g) else np.nan,
            '≥8%命中率': (g >= .08).mean() if len(g) else np.nan,
            '平均5日最大涨幅': g.mean() if len(g) else np.nan,
        })
    idf = pd.DataFrame(rows)
    st.subheader("各共振指标单独效果")
    st.dataframe(
        idf.style.format({
            '≥5%命中率':'{:.1%}','≥8%命中率':'{:.1%}','平均5日最大涨幅':'{:+.2%}'
        }, na_rep=''),
        hide_index=True, use_container_width=True
    )


def render_ranking_diagnostics(bt):
    """Diagnose which A ranking modules distinguish future strong stocks."""
    if bt is None or bt.empty:
        return

    d = bt.copy()
    needed = [
        'Replay Date','Ticker','Replay Eligible Rank','5D Max Gain',
        'Structure Score','Trend & Momentum Score','Accumulation Score','Leadership Score',
        'Replay Core Score 85','MA20 Slope 5D','Volume Build Ratio',
        'Up/Down Volume Ratio','Stock vs SPY 20D','Stock vs Sector 20D'
    ]
    for c in needed:
        if c not in d.columns:
            return

    for c in [
        'Replay Eligible Rank','5D Max Gain','Structure Score','Trend & Momentum Score',
        'Accumulation Score','Leadership Score','Replay Core Score 85','MA20 Slope 5D',
        'Volume Build Ratio','Up/Down Volume Ratio','Stock vs SPY 20D','Stock vs Sector 20D'
    ]:
        d[c] = pd.to_numeric(d[c], errors='coerce')

    d = d.dropna(subset=['5D Max Gain'])
    if d.empty:
        return

    st.header('🔬 A4 Ranking Diagnostic — 强股为什么没进 Top10')
    st.caption(
        '只做诊断，不改变 LIVE 排名权重。重点比较：Top10强股、Top10弱股、'
        '以及被Top10漏掉但未来5日≥5%/≥8%的强股。'
    )

    d['组别'] = '其他'
    d.loc[(d['Replay Eligible Rank'] <= 10) & (d['5D Max Gain'] >= .05), '组别'] = 'Top10强股 ≥5%'
    d.loc[(d['Replay Eligible Rank'] <= 10) & (d['5D Max Gain'] < .02), '组别'] = 'Top10弱股 <2%'
    d.loc[(d['Replay Eligible Rank'] > 10) & (d['5D Max Gain'] >= .08), '组别'] = '漏掉大涨股 ≥8%'
    d.loc[(d['Replay Eligible Rank'] > 10) & (d['5D Max Gain'] >= .05) & (d['5D Max Gain'] < .08), '组别'] = '漏掉强股 5–8%'

    diag_groups = ['Top10强股 ≥5%','Top10弱股 <2%','漏掉强股 5–8%','漏掉大涨股 ≥8%']
    features = [
        'Replay Core Score 85','Structure Score','Trend & Momentum Score',
        'Accumulation Score','Leadership Score','MA20 Slope 5D',
        'Volume Build Ratio','Up/Down Volume Ratio',
        'Stock vs SPY 20D','Stock vs Sector 20D'
    ]

    grp = (
        d[d['组别'].isin(diag_groups)]
        .groupby('组别')[features]
        .agg(['mean','median','count'])
    )
    if not grp.empty:
        # Flatten MultiIndex columns for Streamlit.
        grp.columns = [f'{a} {b}' for a,b in grp.columns]
        grp = grp.reset_index()
        st.subheader('① 四组股票的当天特征对比')
        fmt = {}
        for c in grp.columns:
            if 'MA20 Slope' in c or 'Stock vs SPY' in c or 'Stock vs Sector' in c:
                if 'count' not in c:
                    fmt[c] = '{:.2%}'
            elif c != '组别' and 'count' not in c:
                fmt[c] = '{:.3f}'
        st.dataframe(
            grp.style.format(fmt, na_rep=''),
            hide_index=True,
            use_container_width=True
        )

    # Predictive separation by feature: strong >=5% vs weak <2%.
    strong = d[d['5D Max Gain'] >= .05]
    weak = d[d['5D Max Gain'] < .02]
    rows = []
    for f in features:
        s = pd.to_numeric(strong[f], errors='coerce').dropna()
        w = pd.to_numeric(weak[f], errors='coerce').dropna()
        allv = pd.to_numeric(d[f], errors='coerce').dropna()
        future = d.loc[allv.index, '5D Max Gain'] if len(allv) else pd.Series(dtype=float)
        corr = allv.corr(future) if len(allv) >= 3 else np.nan
        sm, wm = s.mean() if len(s) else np.nan, w.mean() if len(w) else np.nan
        pooled = np.nan
        if len(s) >= 2 and len(w) >= 2:
            denom = np.sqrt((s.var(ddof=1) + w.var(ddof=1)) / 2)
            pooled = (sm - wm) / denom if denom and not pd.isna(denom) else np.nan
        rows.append({
            '特征': f,
            '强股均值(≥5%)': sm,
            '弱股均值(<2%)': wm,
            '强-弱差': sm - wm if not pd.isna(sm) and not pd.isna(wm) else np.nan,
            '标准化区分度': pooled,
            '与5日最大涨幅相关': corr
        })
    sep = pd.DataFrame(rows)
    sep['绝对区分度'] = sep['标准化区分度'].abs()
    sep = sep.sort_values(['绝对区分度','与5日最大涨幅相关'], ascending=[False,False]).drop(columns=['绝对区分度'])

    st.subheader('② 哪个模块最能区分未来强股与弱股')
    fmt2 = {
        '强股均值(≥5%)':'{:.3f}',
        '弱股均值(<2%)':'{:.3f}',
        '强-弱差':'{:+.3f}',
        '标准化区分度':'{:+.3f}',
        '与5日最大涨幅相关':'{:+.3f}',
    }
    st.dataframe(
        sep.style.format(fmt2, na_rep=''),
        hide_index=True,
        use_container_width=True
    )

    # Top/bottom quartile outcome test for each module.
    st.subheader('③ 每个模块高分组 vs 低分组，未来5日表现')
    qrows = []
    module_features = ['Structure Score','Trend & Momentum Score','Accumulation Score','Leadership Score']
    for f in module_features:
        vals = pd.to_numeric(d[f], errors='coerce')
        valid = d[vals.notna()].copy()
        if valid.empty:
            continue
        q25 = valid[f].quantile(.25)
        q75 = valid[f].quantile(.75)
        low = valid[valid[f] <= q25]
        high = valid[valid[f] >= q75]
        for label, x in [('低25%', low), ('高25%', high)]:
            g = pd.to_numeric(x['5D Max Gain'], errors='coerce').dropna()
            qrows.append({
                '模块': f,
                '分组': label,
                '样本': len(g),
                '≥5%命中率': (g >= .05).mean() if len(g) else np.nan,
                '≥8%命中率': (g >= .08).mean() if len(g) else np.nan,
                '平均5日最大涨幅': g.mean() if len(g) else np.nan,
                '中位数5日最大涨幅': g.median() if len(g) else np.nan,
            })
    qdf = pd.DataFrame(qrows)
    if not qdf.empty:
        st.dataframe(
            qdf.style.format({
                '≥5%命中率':'{:.1%}',
                '≥8%命中率':'{:.1%}',
                '平均5日最大涨幅':'{:+.2%}',
                '中位数5日最大涨幅':'{:+.2%}',
            }, na_rep=''),
            hide_index=True,
            use_container_width=True
        )

    # Missed strong stocks: which component is low relative to current Top10 threshold?
    st.subheader('④ 漏掉的 ≥8% 大涨股：为什么排名靠后')
    missed8 = d[(d['Replay Eligible Rank'] > 10) & (d['5D Max Gain'] >= .08)].copy()
    if missed8.empty:
        st.info('当前回放窗口没有漏掉的 ≥8% 大涨股。')
    else:
        cols = [
            'Replay Date','Ticker','Replay Eligible Rank','Replay Core Score 85',
            'Structure Score','Trend & Momentum Score','Accumulation Score','Leadership Score',
            'MA20 Slope 5D','Stock vs SPY 20D','Stock vs Sector 20D','5D Max Gain'
        ]
        show = missed8.sort_values(['5D Max Gain','Replay Eligible Rank'], ascending=[False,True])
        st.dataframe(
            show[[c for c in cols if c in show.columns]].head(100).style.format({
                'MA20 Slope 5D':'{:.2%}',
                'Stock vs SPY 20D':'{:+.2%}',
                'Stock vs Sector 20D':'{:+.2%}',
                '5D Max Gain':'{:+.2%}',
            }, na_rep=''),
            hide_index=True,
            use_container_width=True
        )


def render_historical_a_replay(bt):
    if bt is None or bt.empty:
        st.warning('历史回放没有得到有效样本。')
        return
    # First show the same-window A/B/C decision table.
    render_3way_hardfilter_comparison(bt)
    st.divider()
    render_a4_a5_resonance_comparison(bt)
    st.divider()
    render_a52_ab_comparison(bt)
    st.divider()
    render_ranking_diagnostics(bt)
    st.divider()

    d = bt.copy()
    for c in ['Replay Universe Rank','Replay Eligible Rank','5D Max Gain','5D Close Return','5D Max Drawdown']:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    g = d['5D Max Gain']

    dates_n = d['Replay Date'].nunique()
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric('回放交易日', int(dates_n))
    c2.metric('股票-日期样本', len(d))
    c3.metric('全池 5日≥3%', f'{(g>=.03).mean():.1%}')
    c4.metric('全池 5日≥5%', f'{(g>=.05).mean():.1%}')
    c5.metric('全池 5日≥8%', f'{(g>=.08).mean():.1%}')

    st.subheader('📊 全扫描池 vs Top30 / Top20 / Top10')
    rows = []
    scopes = [
        ('全部扫描池', d),
        ('Hard Filter通过', d[d['Hard Filter']=='通过']),
        ('A Top30', d[d['Replay Eligible Rank']<=30]),
        ('A Top20', d[d['Replay Eligible Rank']<=20]),
        ('A Top10', d[d['Replay Eligible Rank']<=10]),
    ]
    for label, x in scopes:
        gg = pd.to_numeric(x['5D Max Gain'], errors='coerce').dropna()
        rows.append({
            '范围': label, '样本': len(gg),
            '≥3%命中率': (gg>=.03).mean() if len(gg) else np.nan,
            '≥5%命中率': (gg>=.05).mean() if len(gg) else np.nan,
            '≥8%命中率': (gg>=.08).mean() if len(gg) else np.nan,
            '平均5日最大涨幅': gg.mean() if len(gg) else np.nan,
            '中位数5日最大涨幅': gg.median() if len(gg) else np.nan,
        })
    summary = pd.DataFrame(rows)
    st.dataframe(summary.style.format({
        '≥3%命中率':'{:.1%}','≥5%命中率':'{:.1%}','≥8%命中率':'{:.1%}',
        '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    strong = d[d['5D Max Gain'] >= .05].copy()
    if not strong.empty:
        top10_capture = (strong['Replay Eligible Rank'] <= 10).fillna(False).mean()
        top20_capture = (strong['Replay Eligible Rank'] <= 20).fillna(False).mean()
        hf_capture = strong['Replay Eligible Rank'].notna().mean()
        a,b,c,dcol = st.columns(4)
        a.metric('≥5%强股总数', len(strong))
        b.metric('通过Hard Filter', f'{hf_capture:.1%}')
        c.metric('进入Top20', f'{top20_capture:.1%}')
        dcol.metric('进入Top10', f'{top10_capture:.1%}')

    render_hard_filter_diagnostics(d)

    st.subheader('🚀 漏掉的强股：后来5日≥5%，但没进A Top10')
    missed = d[(d['5D Max Gain']>=.05) & (~d['Replay Top10'])].copy()
    missed = missed.sort_values(['5D Max Gain','Replay Universe Rank'], ascending=[False,True])
    cols = ['Replay Date','Ticker','Sector','Replay Universe Rank','Replay Eligible Rank','Hard Filter','Hard Filter Reason',
            'Replay Core Score 85','Structure Score','Trend & Momentum Score','Accumulation Score','Leadership Score',
            'MA20 Slope 5D','RS Acceleration','5D Max Gain','5D Close Return','5D Max Drawdown']
    show = missed[[c for c in cols if c in missed.columns]].head(100)
    fmt = {'MA20 Slope 5D':'{:.2%}','5D Max Gain':'{:+.2%}','5D Close Return':'{:+.2%}','5D Max Drawdown':'{:+.2%}'}
    st.dataframe(show.style.format({k:v for k,v in fmt.items() if k in show.columns}, na_rep=''), hide_index=True, use_container_width=True)

    st.subheader('🔎 强股 vs 弱股：A当天特征')
    tmp = d.copy()
    tmp['组别'] = np.where(tmp['5D Max Gain']>=.05, '强股 ≥5%', np.where(tmp['5D Max Gain']<.02, '弱股 <2%', '普通 2–5%'))
    features = ['Replay Core Score 85','Structure Score','Trend & Momentum Score','Accumulation Score','Leadership Score',
                'MA20 Slope 5D','Volume Build Ratio','Up/Down Volume Ratio','Stock vs SPY 20D','Stock vs Sector 20D']
    available = [c for c in features if c in tmp.columns]
    grp = tmp.groupby('组别')[available].mean(numeric_only=True).reset_index()
    st.dataframe(grp.style.format({c:'{:.3f}' for c in available}, na_rep=''), hide_index=True, use_container_width=True)

    csv = d.to_csv(index=False).encode('utf-8-sig')
    st.download_button('💾 下载历史A回放明细', csv,
                       file_name=f"V43A_Historical_Replay_{dates_n}D_{datetime.now().strftime('%Y-%m-%d')}.csv",
                       mime='text/csv', use_container_width=True)

# =========================================================
# UI
# =========================================================
with st.sidebar:
    st.header("V4.3A.5.2 图形共振A/B测试设置")
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
    st.success("V4.3A.4 正式规则：仅放宽 MA200；MA20、MA50、MA20斜率≥0.2%、Structure 均保留。")

st.info(
    "LIVE A当前正式采用MA200-only：约1年日K → 五大模块 → 原Hard Filter → Fundamental Confirmation → Early V2排名 → 次日Top候选。"
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

    st.success(f"✅ V4.3A.4 扫描完成：{len(top_df)}只次日重点候选")

    display_cols = [
        # 结果放最前；最终只给“买 / 不买”
        "A5决策", "Rank", "Ticker", "Company", "Price", "共振数",
        # 一个指标一个col
        "图形共振", "图形形态", "MACD共振", "KDJ共振", "RSI共振", "量价共振", "RS共振",
        # 关键数值，便于复核
        "Early V2 Score", "Structure Score", "Trend & Momentum Score",
        "Accumulation Score", "Leadership Score",
        "KDJ_K", "KDJ_D", "KDJ_J", "RSI14", "MACD Phase",
        "Volume Build Ratio", "Up/Down Volume Ratio", "RS Acceleration",
        "Major Resistance Zone", "Major Support Zone",
        "Confidence"
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
        "A5决策":"结果", "共振数":"共振数", "图形共振":"图形", "图形形态":"形态", "假突破":"假突破", "MACD共振":"MACD", "KDJ共振":"KDJ", "RSI共振":"RSI", "量价共振":"量价", "RS共振":"相对强度", "KDJ_K":"K", "KDJ_D":"D", "KDJ_J":"J",
        "Rank":"排名", "Ticker":"股票代码", "Company":"公司", "Early V2 Score":"Early V2总分",
        "Confidence":"信心等级", "Fundamental Confirmation":"基本面确认", "Fundamental Reason":"基本面依据",
        "Quality Fundamental":"质量", "FCF Fundamental":"现金流", "Debt Fundamental":"负债",
        "Valuation Fundamental":"估值", "Growth Fundamental":"增长",
        "Structure Score":"市场结构分", "Trend & Momentum Score":"趋势动量分",
        "Accumulation Score":"资金积累分", "Leadership Score":"相对强势分", "Catalyst Score":"催化剂分",
        "Price":"当前价格", "Major Resistance Zone":"主要压力区", "Resistance Touches":"压力测试次数",
        "Major Support Zone":"主要支撑区",
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
st.header("🔥 A历史强股回测 — 过去行情直接Replay")
st.caption(
    "不用等未来5天。程序会回到过去每个交易日，用当时已有的日K重新扫描整个股票池，再查看随后1/3/5个交易日的真实表现。"
)
st.info(
    "为避免偷看未来：历史Replay只使用能够从历史日K真实重建的 A 核心85分（结构25 + 趋势20 + 资金20 + 领导力20）。"
    "Yahoo当前News无法可靠还原过去某一天的Catalyst，因此历史Catalyst不参与Replay排名；Fundamental本来就不进入Early V2 100分。"
)

r1, r2 = st.columns([1,2])
with r1:
    replay_days = st.selectbox("回放多少个历史交易日", [20,30,60], index=2)
with r2:
    st.caption("现在建议直接跑60日：同一窗口一次比较 A3 Control、MA200-only、MA20+MA200。最近5个交易日只作为未来结果窗口。")

if st.button("🧪 运行 60日三版本同屏回测", type="primary", use_container_width=True):
    try:
        p = st.progress(0)
        s = st.empty()
        bt = run_historical_a_replay(replay_days=int(replay_days), progress_bar=p, status_box=s)
        st.session_state["a_historical_replay"] = bt
        st.session_state["a_historical_replay_days"] = int(replay_days)
    except Exception as e:
        st.error(f"A历史回测失败：{e}")

if "a_historical_replay" in st.session_state:
    _cached_bt = st.session_state["a_historical_replay"]
    _need_cols = {'A5决策','图形共振','RS共振'}
    if not _need_cols.issubset(set(_cached_bt.columns)):
        st.info("检测到旧版本历史回测缓存。A5.1 图形字段尚未生成，请重新点击上面的 60 日回测按钮。")
    render_historical_a_replay(_cached_bt)

with st.expander("查看 Forward Validation 历史库（从现在开始每天自动积累）"):
    if "a_all_history_save_msg" in st.session_state:
        st.info(st.session_state["a_all_history_save_msg"])
    st.caption("A_AllScannedHistory 保留用于以后做真实的前瞻验证，但它不是历史Replay的前提。历史Replay现在可以立刻运行。")
    if st.button("运行已保存历史库的Forward Validation", use_container_width=True):
        try:
            hist = load_all_scan_history()
            if hist.empty:
                st.warning("A_AllScannedHistory 还没有记录。")
            else:
                bt_fwd = evaluate_scan_history(hist)
                st.session_state["a_strong_bt"] = bt_fwd
        except Exception as e:
            st.error(f"Forward Validation失败：{e}")
    if "a_strong_bt" in st.session_state:
        render_strong_stock_backtest(st.session_state["a_strong_bt"])

