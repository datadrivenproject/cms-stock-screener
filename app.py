import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import time
from datetime import datetime, timezone
from universe_1500 import build_universe as build_composite_universe
from a_selection_core import classify_current_a

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

# =========================================================
# PAGE
# =========================================================

st.set_page_config(page_title="CMS 股票控制台", page_icon="📈", layout="wide")

st.title("📈 CMS 股票控制台")
st.caption("轻量版 · 今日候选 / 正式优选 / 卖出检查")

# ===== 页面显示：Supabase 最后数据日期 =====
@st.cache_data(ttl=300, show_spinner=False)
def get_supabase_last_data_date():
    """
    页面打开时直接查询 Supabase stock_daily 的最新 trade_date。
    不依赖先运行扫描，也不用今天日期冒充行情日期。
    """
    try:
        def find_secret(name):
            # 顶层 Secrets
            try:
                if name in st.secrets:
                    return st.secrets[name]
            except Exception:
                pass

            # 支持 TOML 分组
            try:
                def walk(obj):
                    if hasattr(obj, "items"):
                        for k, v in obj.items():
                            if str(k) == name:
                                return v
                            found = walk(v)
                            if found is not None:
                                return found
                    return None
                return walk(st.secrets)
            except Exception:
                return None

        base_url = find_secret("SUPABASE_URL")
        api_key = find_secret("SUPABASE_SERVICE_ROLE_KEY")

        if not base_url or not api_key:
            return "未知"

        base_url = str(base_url).strip().rstrip("/")
        api_key = str(api_key).strip()

        if "/rest/v1" in base_url:
            base_url = base_url.split("/rest/v1", 1)[0].rstrip("/")

        endpoint = f"{base_url}/rest/v1/stock_daily"
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        params = {
            "select": "trade_date",
            "order": "trade_date.desc",
            "limit": "1",
        }

        r = requests.get(endpoint, headers=headers, params=params, timeout=15)
        if r.status_code >= 400:
            return "未知"

        rows = r.json()
        if not rows:
            return "未知"

        dt = pd.to_datetime(rows[0].get("trade_date"), errors="coerce")
        if pd.isna(dt):
            return "未知"

        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "未知"


_page_last_date = get_supabase_last_data_date()
st.info(f"📅 Supabase 最后数据日期：{_page_last_date}")


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
# UNIVERSE — A6 FINAL 500 POOL
# =========================================================
# 保留原来的自选成长/热门股，同时自动加入 S&P 500。
# S&P 500 成分会变化，因此不在程序里硬编码 500 个代码。
# 若网络临时无法读取成分表，会自动退回原自选池，不影响 App 启动。


@st.cache_data(ttl=21600, show_spinner=False)
def get_universe():
    """Current S&P Composite 1500 plus the preserved CMS core/watchlist."""
    return build_composite_universe(verbose=False)

# =========================================================
# DOWNLOAD HELPERS
# =========================================================
def split_chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]



# =========================================================
# SUPABASE DAILY OHLCV — production scan data source
# The frozen A5.2R decision logic below is unchanged.
# GitHub Actions keeps public.stock_daily updated.
# Streamlit Cloud must have these top-level secrets:
#   SUPABASE_URL
#   SUPABASE_SERVICE_ROLE_KEY
# =========================================================
def _find_streamlit_secret(key):
    """
    Find a secret by name anywhere in st.secrets.

    Why recursive:
    Existing CMS Streamlit secrets already contain TOML sections such as
    [gcp_service_account] / [tracker]. If SUPABASE_* lines are pasted after
    a section header, TOML is valid but those values become nested inside
    that section instead of being top-level. This helper supports both
    top-level and accidentally nested placement without exposing values.
    """
    try:
        root = st.secrets
    except Exception:
        return None

    # Top-level first.
    try:
        if key in root:
            value = root[key]
            if value is not None and str(value).strip():
                return str(value).strip()
    except Exception:
        pass

    # Recursive search through TOML sections.
    def walk(obj):
        try:
            items = obj.items()
        except Exception:
            return None

        for k, v in items:
            if str(k) == key:
                try:
                    text = str(v).strip()
                except Exception:
                    text = ""
                if text:
                    return text

            # Streamlit Secrets sections behave like mappings.
            try:
                if hasattr(v, "items"):
                    found = walk(v)
                    if found:
                        return found
            except Exception:
                pass
        return None

    return walk(root)


def _get_supabase_runtime_config():
    base_url = _find_streamlit_secret("SUPABASE_URL")
    api_key = _find_streamlit_secret("SUPABASE_SERVICE_ROLE_KEY")

    missing = []
    if not base_url:
        missing.append("SUPABASE_URL")
    if not api_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")

    if missing:
        raise RuntimeError(
            "Streamlit Secrets 未读取到：" + ", ".join(missing) +
            "。请确认这两个名称拼写完全一致；程序已同时支持顶层和 TOML 分组内的 Secrets。"
        )

    base_url = str(base_url).strip().rstrip("/")
    api_key = str(api_key).strip()

    if "/rest/v1" in base_url:
        base_url = base_url.split("/rest/v1", 1)[0].rstrip("/")

    if not base_url.startswith("https://") or not base_url.endswith(".supabase.co"):
        raise RuntimeError(
            "SUPABASE_URL 格式不正确。应类似 https://xxxx.supabase.co，且不要包含 /rest/v1/。"
        )

    return base_url, api_key


def _supabase_headers(api_key):
    return {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _daily_rows_to_df(rows):
    """Convert Supabase adjusted OHLCV rows to the exact dataframe shape A5.2R expects.

    Production A intentionally requires adj_open/adj_high/adj_low/adj_close.
    It does NOT silently fall back to raw OHLC, because mixing adjusted and
    unadjusted price histories can change MACD/RSI/RS/support-resistance results.
    """
    if not rows:
        return None
    d = pd.DataFrame(rows)
    required = ["trade_date", "adj_open", "adj_high", "adj_low", "adj_close", "volume"]
    if any(c not in d.columns for c in required):
        return None

    d["trade_date"] = pd.to_datetime(d["trade_date"], errors="coerce")
    d = d.dropna(subset=["trade_date"]).sort_values("trade_date")
    d = d.drop_duplicates(subset=["trade_date"], keep="last")

    for c in ["adj_open", "adj_high", "adj_low", "adj_close", "volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    d = d.dropna(subset=["adj_open", "adj_high", "adj_low", "adj_close", "volume"])
    if d.empty:
        return None

    d = d.set_index("trade_date")
    d.index.name = "Date"

    return d[["adj_open", "adj_high", "adj_low", "adj_close", "volume"]].rename(columns={
        "adj_open":"Open",
        "adj_high":"High",
        "adj_low":"Low",
        "adj_close":"Close",
        "volume":"Volume",
    })


@st.cache_data(ttl=1800, show_spinner=False)
def supabase_batch_download(tickers_tuple):
    """Load all available stock_daily rows for tickers from Supabase.

    REST is paginated explicitly so the PostgREST row limit does not silently
    truncate the universe. Returned frames intentionally match the OHLCV shape
    used by the frozen A5.2R analyzer.
    """
    tickers = [str(t).upper().strip() for t in tickers_tuple if str(t).strip()]
    if not tickers:
        return {}

    base_url, api_key = _get_supabase_runtime_config()
    endpoint = f"{base_url}/rest/v1/stock_daily"
    headers = _supabase_headers(api_key)
    rows_by_ticker = {t: [] for t in tickers}

    # Keep URL size modest and paginate every chunk.
    for chunk in split_chunks(tickers, 20):
        ticker_filter = "in.(" + ",".join(chunk) + ")"
        start = 0
        page_size = 1000
        while True:
            params = {
                "select": "ticker,trade_date,adj_open,adj_high,adj_low,adj_close,volume",
                "ticker": ticker_filter,
                "order": "ticker.asc,trade_date.asc",
            }
            h = dict(headers)
            h["Range"] = f"{start}-{start + page_size - 1}"
            r = requests.get(endpoint, params=params, headers=h, timeout=60)
            if not r.ok:
                raise RuntimeError(f"Supabase stock_daily 读取失败 HTTP {r.status_code}: {r.text[:500]}")
            page = r.json()
            for row in page:
                t = str(row.get("ticker", "")).upper()
                if t in rows_by_ticker:
                    rows_by_ticker[t].append(row)
            if len(page) < page_size:
                break
            start += page_size

    out = {}
    for t, rows in rows_by_ticker.items():
        df = _daily_rows_to_df(rows)
        if df is not None and not df.empty:
            out[t] = df
    return out




@st.cache_data(ttl=1800, show_spinner=False)

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
# Legacy indicator calculations retained for reference; NOT part of KD 20/80 trade decision
# One indicator = one column. Final decision is only 买 / 不买.
# =========================================================
def calc_a5_resonance(df, row=None):
    """
    A5.2R = Resonance + calculated Support/Resistance.
    No Vision / no chart-image AI.

    Keeps:
      MACD + KDJ + RSI + Price/Volume + RS
    Removes from decision:
      the old crude "near prior 20D high" breakout resonance
    Adds:
      swing-based support/resistance zones + upside-room check
    """
    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    if len(close.dropna()) < 60:
        return {}

    # ---------- 势：MACD ----------
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    hist = macd - sig
    # Positive MACD resonance must be strong NOW, not merely have strengthened yesterday.
    # Require current positive histogram to be non-shrinking vs the prior bar.
    macd_ok = bool(
        (macd.iloc[-1] > sig.iloc[-1]) and
        (hist.iloc[-1] > 0) and
        (hist.iloc[-1] >= hist.iloc[-2])
    )

    # ---------- 势：KDJ (9,3,3) ----------
    ll9 = low.rolling(9).min()
    hh9 = high.rolling(9).max()
    rsv = (close - ll9) / (hh9 - ll9).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    k0, d0, j0 = safe_num(k.iloc[-1]), safe_num(d.iloc[-1]), safe_num(j.iloc[-1])
    k1, d1 = safe_num(k.iloc[-2]), safe_num(d.iloc[-2])
    # Positive KDJ resonance requires K>D and both K/D to be non-declining today.
    # This prevents a high-level bearish turn from still being counted as positive resonance.
    kdj_ok = bool(
        (k0 > d0) and
        (k0 >= 45) and
        (j0 <= 110) and
        (k0 >= k1) and
        (d0 >= d1)
    )

    # ---------- 势：RSI ----------
    rsi_series = calc_rsi(close, 14)
    rsi = safe_num(rsi_series.iloc[-1])
    rsi_prev = safe_num(rsi_series.iloc[-2])
    rsi_prev2 = safe_num(rsi_series.iloc[-3]) if len(rsi_series) >= 3 else np.nan

    # 旧 RSI 共振字段仅为兼容历史代码，不再决定正式候选。
    rsi_ok = bool((50 <= rsi <= 72) and (rsi >= rsi_prev))

    # ---------- RSI 超卖回升（新研究层） ----------
    # B1：过去3个交易日（含今天）至少一次 RSI<=30，并且今天 RSI 比昨天上升。
    #     这是较早的“超卖后开始回升”信号。
    recent_rsi3 = pd.to_numeric(rsi_series.tail(3), errors="coerce")
    rsi_was_oversold = bool(
        recent_rsi3.notna().any()
        and (recent_rsi3.min() <= 30)
    )
    rsi_turn_up = bool(
        (not pd.isna(rsi))
        and (not pd.isna(rsi_prev))
        and (rsi > rsi_prev)
    )
    rsi_oversold_rebound = bool(rsi_was_oversold and rsi_turn_up)

    # B2：更严格确认——昨天 RSI<=30，今天重新站上30。
    rsi_cross_30 = bool(
        (not pd.isna(rsi))
        and (not pd.isna(rsi_prev))
        and (rsi_prev <= 30)
        and (rsi > 30)
    )

    # ---------- CMS 新核心：KD 20/80 ----------
    # 只用 K、D 的交叉和当前位置做交易触发。
    # MACD / RSI / 量价 / RS 不再决定买卖。
    #
    # BUY（真正的20低位金叉）：
    #   1) 昨日 K <= D
    #   2) 今日 K > D   -> 今日发生金叉
    #   3) 今日 K <= 20 且今日 D <= 20
    #
    # SELL（真正的80高位死叉）：
    #   1) 昨日 K >= D
    #   2) 今日 K < D   -> 今日发生死叉
    #   3) 今日 K >= 80 且今日 D >= 80
    kd_diff = k - d
    kd_cross_up_today = bool((kd_diff.iloc[-1] > 0) and (kd_diff.iloc[-2] <= 0))
    kd_cross_down_today = bool((kd_diff.iloc[-1] < 0) and (kd_diff.iloc[-2] >= 0))

    # 位置判断只看“交叉当天”，不再回看昨天是否碰过20/80。
    # 因此 AMAT 这类当前 K > 20 的股票不会再被算作20低位金叉。
    kd_low_20 = bool((k0 <= 20) and (d0 <= 20))
    kd_high_80 = bool((k0 >= 80) and (d0 >= 80))

    kd_buy = bool(kd_cross_up_today and kd_low_20)
    kd_sell = bool(kd_cross_down_today and kd_high_80)

    # 三套买入研究信号：
    # A  = 纯 KD20 低位金叉（当前基准）
    # B1 = KD20 金叉 + RSI 曾超卖且今天回升
    # B2 = KD20 金叉 + RSI 昨日<=30、今日重新站上30
    kd_rsi_rebound_buy = bool(kd_buy and rsi_oversold_rebound)
    kd_rsi_cross30_buy = bool(kd_buy and rsi_cross_30)

    if kd_rsi_cross30_buy:
        signal_group = "B2 KD+RSI上穿30"
    elif kd_rsi_rebound_buy:
        signal_group = "B1 KD+RSI超卖回升"
    elif kd_buy:
        signal_group = "A 纯KD20金叉"
    else:
        signal_group = "无买入信号"

    kd_action = "买" if kd_buy else ("卖" if kd_sell else "观察")

    # 仅用于排序/展示，不参与是否触发。
    kd_buy_zone = max(k0, d0) if kd_buy else np.nan
    kd_sell_zone = min(k0, d0) if kd_sell else np.nan

    # ---------- 量：Price / Volume ----------
    avg20v = safe_num(volume.rolling(20).mean().iloc[-1])
    rvol = safe_num(volume.iloc[-1] / avg20v) if avg20v > 0 else np.nan
    ret1 = safe_num(close.iloc[-1] / close.iloc[-2] - 1)
    avg5v = safe_num(volume.rolling(5).mean().iloc[-1])
    vbuild = safe_num(avg5v / avg20v) if avg20v > 0 else np.nan
    pv_ok = bool(
        ((ret1 > 0) and (rvol >= 1.10))
        or ((vbuild >= 1.05) and (close.iloc[-1] >= close.rolling(10).mean().iloc[-1]))
    )

    # ---------- 势：Relative Strength ----------
    # FIX3: RS Acceleration is stored by score_leadership() as Chinese text
    # ("是"/"否"), not as a numeric 1/0.  FIX2 passed that text through
    # safe_num(), which converted it to NaN and therefore made RS共振 always false.
    # Accept the intended text/boolean representation while remaining backward
    # compatible with numeric cached values.
    rs_acc_raw = (row or {}).get("RS Acceleration", np.nan)
    if isinstance(rs_acc_raw, str):
        rs_acc_ok = rs_acc_raw.strip().lower() in {"是", "yes", "true", "1", "y"}
    elif isinstance(rs_acc_raw, (bool, np.bool_)):
        rs_acc_ok = bool(rs_acc_raw)
    else:
        rs_acc_num = safe_num(rs_acc_raw)
        rs_acc_ok = bool((not pd.isna(rs_acc_num)) and (rs_acc_num > 0))

    rs20 = safe_num((row or {}).get("Stock vs SPY 20D", np.nan))
    rs_ok = bool(
        rs_acc_ok
        and (not pd.isna(rs20)) and (rs20 > 0)
    )

    # ---------- 位置：用OHLCV计算真实价格反应区 ----------
    px = safe_num(close.iloc[-1])
    atr14 = safe_num(calc_atr(high, low, close, 14).iloc[-1])
    ms = identify_market_structure(df, atr14, px)

    major_res = ms.get("major_res")
    major_sup = ms.get("major_sup")

    if major_res is not None:
        res_zone = f"${major_res['low']:.2f}–${major_res['high']:.2f}"
        resistance_distance = (major_res["low"] - px) / px if px > 0 else np.nan
        resistance_touches = int(major_res.get("touches", 0))
        resistance_strength = _zone_strength(major_res)
        inside_resistance = bool(
            major_res["low"] * 0.995 <= px <= major_res["high"] * 1.005
        )
    else:
        res_zone = "未识别"
        resistance_distance = np.nan
        resistance_touches = 0
        resistance_strength = "无有效区域"
        inside_resistance = False

    if major_sup is not None:
        sup_zone = f"${major_sup['low']:.2f}–${major_sup['high']:.2f}"
        # distance from price to upper edge of nearest support
        support_distance = (px - major_sup["high"]) / px if px > 0 else np.nan
        support_touches = int(major_sup.get("touches", 0))
    else:
        sup_zone = "未识别"
        support_distance = np.nan
        support_touches = 0

    # "上方空间" / 支撑压力现在只作为位置与风险信息，不再拥有一票否决权。
    # 保留原来的“压力过近”识别，供 A 页面、Google Sheet、B/Unified 后续参考；
    # 但它不再改变 A 的“买 / 不买”核心决定。
    pressure_too_close = bool(
        major_res is not None
        and resistance_touches >= 2
        and (
            inside_resistance
            or (
                not pd.isna(resistance_distance)
                and 0 <= resistance_distance < 0.02
            )
        )
    )
    space_ok = not pressure_too_close

    if major_res is None:
        upside_room_text = "开放"
    elif pd.isna(resistance_distance):
        upside_room_text = "不确定"
    else:
        upside_room_text = f"{resistance_distance:+.1%}"

    # ---------- A5.2R final ----------
    # Old crude breakout resonance is intentionally removed.
    # Five core confirmations: MACD / KDJ / RSI / 量价 / RS.
    core_flags = [macd_ok, kdj_ok, rsi_ok, pv_ok, rs_ok]
    resonance_n = int(sum(core_flags))

    # Legacy startup diagnostics retained for reference only
    # Goal: identify the transition from accumulation/base -> ignition,
    # rather than simply requiring every indicator to be rising today.
    #
    # This layer is designed around the type of entry we want to study:
    # ORCL around Sep-01, LITE around Jul-30, and the current PSX setup.
    # It uses only as-of-date OHLCV and does NOT use MA200.

    ret5_now = safe_num((row or {}).get("5D Return", np.nan))

    # 1) Fresh MACD ignition: histogram crossed above zero recently OR
    #    is clearly accelerating versus 3 sessions ago.
    hist_prev = hist.shift(1)
    macd_cross_recent = bool(
        ((hist.tail(5) > 0) & (hist_prev.tail(5) <= 0)).fillna(False).any()
    )
    hist_3ago = safe_num(hist.iloc[-4]) if len(hist) >= 4 else np.nan
    macd_accel = bool(
        (not pd.isna(hist_3ago))
        and (hist.iloc[-1] > 0)
        and (hist.iloc[-1] > hist_3ago)
    )
    fresh_macd = bool(macd_cross_recent or macd_accel)

    # 2) Fresh KDJ turn: K crossed above D within the last 5 sessions,
    #    or K is rising from a non-overheated zone.
    kd_diff = k - d
    kd_prev = kd_diff.shift(1)
    kdj_cross_recent = bool(
        ((kd_diff.tail(5) > 0) & (kd_prev.tail(5) <= 0)).fillna(False).any()
    )
    k_3ago = safe_num(k.iloc[-4]) if len(k) >= 4 else np.nan
    kdj_turn = bool(
        (k0 > d0)
        and (not pd.isna(k_3ago))
        and (k0 > k_3ago)
        and (k0 < 85)
    )
    fresh_kdj = bool(kdj_cross_recent or kdj_turn)

    # 3) Volume ignition: either one of the last 3 sessions showed >=1.10 RVOL
    #    on an up day, or recent average volume is building above the 20D base.
    avg20_series = volume.rolling(20).mean()
    rvol_series = volume / avg20_series.replace(0, np.nan)
    up_day = close.pct_change() > 0
    recent_volume_ignition = bool(
        ((rvol_series.tail(3) >= 1.10) & up_day.tail(3)).fillna(False).any()
        or (not pd.isna(vbuild) and vbuild >= 1.05)
    )

    # 4) Pre-launch contraction/base: compare the range BEFORE the last 3 bars
    #    with the preceding 20-session range.  We want some evidence that price
    #    had compressed before the current ignition.
    prior = df.iloc[:-3].copy() if len(df) > 23 else df.iloc[:-1].copy()
    prior_high10 = safe_num(pd.to_numeric(prior["High"], errors="coerce").tail(10).max())
    prior_low10 = safe_num(pd.to_numeric(prior["Low"], errors="coerce").tail(10).min())
    prior_high20 = safe_num(pd.to_numeric(prior["High"], errors="coerce").tail(20).max())
    prior_low20 = safe_num(pd.to_numeric(prior["Low"], errors="coerce").tail(20).min())
    range10 = ((prior_high10 - prior_low10) / prior_low10) if prior_low10 > 0 else np.nan
    range20 = ((prior_high20 - prior_low20) / prior_low20) if prior_low20 > 0 else np.nan
    compression_ratio = (range10 / range20) if (not pd.isna(range20) and range20 > 0) else np.nan
    base_compression = bool(not pd.isna(compression_ratio) and compression_ratio <= 0.75)

    # 5) Position around a 20D pivot: early entries are preferred before the
    #    stock is already far above its prior 20-session high.
    pivot20 = safe_num(high.shift(1).rolling(20).max().iloc[-1])
    pivot_ext = ((px - pivot20) / pivot20) if (not pd.isna(pivot20) and pivot20 > 0) else np.nan
    pivot_early = bool(
        pd.isna(pivot_ext)
        or (-0.05 <= pivot_ext <= 0.04)
    )

    # 6) Avoid clearly mature 5D moves, but keep the band wide enough that a
    #    genuine breakout is not rejected simply because it has already started.
    not_mature_5d = bool(pd.isna(ret5_now) or ret5_now <= 0.12)

    startup_flags = [
        fresh_macd,
        fresh_kdj,
        recent_volume_ignition,
        base_compression,
        pivot_early,
        not_mature_5d,
    ]
    startup_score = int(sum(startup_flags))

    # Startup Transition V3:
    # A genuine launch should not be supported by only one isolated trigger.
    # Require at least TWO of MACD / KDJ / volume to show fresh ignition,
    # plus at least one location/context confirmation (compression or early pivot).
    fresh_trigger_count = int(sum([
        fresh_macd,
        fresh_kdj,
        recent_volume_ignition,
    ]))
    fresh_trigger = bool(fresh_trigger_count >= 2)
    location_context = bool(base_compression or pivot_early)

    # 正式交易决定已经切换为 KD 20/80。
    # 为兼容现有下游表格，A5决策继续保留字段名，但内容只由 KD 买入信号决定。
    base_buy = kd_buy
    decision = "买" if kd_buy else "不买"

    if pressure_too_close:
        position_reason = "压力过近"
    elif major_res is None:
        position_reason = "上方开放"
    else:
        position_reason = "空间通过"

    return {
        "A5决策": decision,
        "共振数": resonance_n,
        "启动阶段": (
            "启动转换" if base_buy else
            "接近启动" if (fresh_trigger and startup_score >= 3) else
            "非启动阶段"
        ),
        "启动分": startup_score,
        "新鲜触发": "是" if fresh_trigger else "否",
        "新鲜触发数": fresh_trigger_count,
        "位置确认": "是" if location_context else "否",
        "MACD启动": "是" if fresh_macd else "否",
        "KDJ启动": "是" if fresh_kdj else "否",
        "量能启动": "是" if recent_volume_ignition else "否",
        "前期压缩": "是" if base_compression else "否",
        "Pivot早期": "是" if pivot_early else "否",
        "压缩比_启动": compression_ratio,
        "Pivot延伸_启动": pivot_ext,
        "5日涨幅_启动判断": ret5_now,
        "MACD共振": "是" if macd_ok else "否",
        "KDJ共振": "是" if kdj_ok else "否",
        "RSI共振": "是" if rsi_ok else "否",
        "量价共振": "是" if pv_ok else "否",
        "RS共振": "是" if rs_ok else "否",
        "空间共振": "是" if space_ok else "否",
        "位置判断": position_reason,
        "A5.2R压力区": res_zone,
        "A5.2R支撑区": sup_zone,
        "上方空间": resistance_distance,
        "距支撑区": support_distance,
        "压力测试次数_A52R": resistance_touches,
        "支撑测试次数_A52R": support_touches,
        "压力强度_A52R": resistance_strength,
        "KDJ_K": k0, "KDJ_D": d0, "KDJ_J": j0,
        "RSI14_新": rsi,
        "RSI昨日": rsi_prev,
        "RSI前日": rsi_prev2,
        "RSI近3日曾超卖": "是" if rsi_was_oversold else "否",
        "RSI今日回升": "是" if rsi_turn_up else "否",
        "RSI超卖回升": "是" if rsi_oversold_rebound else "否",
        "RSI上穿30": "是" if rsi_cross_30 else "否",
        "KD+RSI超卖回升": "是" if kd_rsi_rebound_buy else "否",
        "KD+RSI上穿30": "是" if kd_rsi_cross30_buy else "否",
        "信号分组": signal_group,
        "KD交易动作": kd_action,
        "KD低位金叉20": "是" if kd_buy else "否",
        "KD高位死叉80": "是" if kd_sell else "否",
        "KD当日金叉": "是" if kd_cross_up_today else "否",
        "KD当日死叉": "是" if kd_cross_down_today else "否",
        "KD低位20": "是" if kd_low_20 else "否",
        "KD高位80": "是" if kd_high_80 else "否",
        "KD买入区值": kd_buy_zone,
        "KD卖出区值": kd_sell_zone,
        "当日RVOL_A5": rvol,
    }


# =========================================================
# VP1 — VOLUME-PRICE PHASE (TEST LAYER; DOES NOT CHANGE FIX3 DECISION)
# =========================================================

# =========================================================
# MODULE 3 — ACCUMULATION (MAX 20)
# =========================================================

def calc_explainable_accumulation(df):
    """
    可解释资金积累评分，满分20。
    目的不是识别真正的“主力身份”，而是用OHLCV观察承接/卖压衰竭迹象。

    四个分项，各0–5分：
      1) OBV改善
      2) 下跌缩量
      3) 上涨放量
      4) 量价背离 / 卖压衰竭
    """
    out = {
        "资金积累总分": 0,
        "OBV改善分": 0,
        "下跌缩量分": 0,
        "上涨放量分": 0,
        "量价背离分": 0,
        "资金积累解释": "",
    }

    try:
        d = _norm_daily_index(df).copy()
        if len(d) < 25:
            out["资金积累解释"] = "历史不足25日"
            return out

        close = pd.to_numeric(d["Close"], errors="coerce")
        volume = pd.to_numeric(d["Volume"], errors="coerce")
        if close.isna().all() or volume.isna().all():
            out["资金积累解释"] = "价格/成交量不足"
            return out

        # OBV
        direction = np.sign(close.diff()).fillna(0)
        obv = (direction * volume.fillna(0)).cumsum()

        # ---------- 1) OBV改善 0–5 ----------
        obv_score = 0
        if len(obv) >= 6 and obv.iloc[-1] > obv.iloc[-6]:
            obv_score += 2
        if len(obv) >= 11 and obv.iloc[-1] > obv.iloc[-11]:
            obv_score += 1
        obv_ma5 = obv.rolling(5).mean()
        if len(obv_ma5.dropna()) >= 2 and obv_ma5.iloc[-1] > obv_ma5.iloc[-2]:
            obv_score += 1
        # 价格5日仍弱，但OBV不弱：额外承接迹象
        ret5 = pct_return(close, 5)
        obv_ret5 = (
            (obv.iloc[-1] - obv.iloc[-6]) / max(abs(obv.iloc[-6]), 1)
            if len(obv) >= 6 else np.nan
        )
        if (not pd.isna(ret5)) and ret5 < 0 and (not pd.isna(obv_ret5)) and obv_ret5 >= 0:
            obv_score += 1
        obv_score = min(5, obv_score)

        # ---------- 2) 下跌缩量 0–5 ----------
        down_score = 0
        ret1 = close.pct_change()
        recent = pd.DataFrame({"ret": ret1, "vol": volume}).tail(10)
        down_days = recent[recent["ret"] < 0]
        vol_ma20 = volume.rolling(20).mean().iloc[-1]

        if len(down_days) >= 2 and np.isfinite(vol_ma20) and vol_ma20 > 0:
            down_avg = down_days["vol"].mean()
            ratio = down_avg / vol_ma20
            if ratio <= 0.75:
                down_score += 3
            elif ratio <= 0.90:
                down_score += 2
            elif ratio <= 1.00:
                down_score += 1

        # 最近下跌日量能逐渐减弱
        if len(down_days) >= 3:
            last3 = down_days["vol"].tail(3).values
            if last3[-1] < last3[-2] < last3[-3]:
                down_score += 2
            elif last3[-1] < last3[-2]:
                down_score += 1
        down_score = min(5, down_score)

        # ---------- 3) 上涨放量 0–5 ----------
        up_score = 0
        up_days = recent[recent["ret"] > 0]
        if len(up_days) >= 2 and len(down_days) >= 2:
            up_avg = up_days["vol"].mean()
            down_avg = down_days["vol"].mean()
            if down_avg > 0:
                uv_ratio = up_avg / down_avg
                if uv_ratio >= 1.40:
                    up_score += 3
                elif uv_ratio >= 1.20:
                    up_score += 2
                elif uv_ratio >= 1.05:
                    up_score += 1

        # 最近上涨日是否明显高于20日均量
        if len(up_days) >= 1 and np.isfinite(vol_ma20) and vol_ma20 > 0:
            last_up_vol = up_days["vol"].iloc[-1]
            if last_up_vol >= 1.30 * vol_ma20:
                up_score += 2
            elif last_up_vol >= 1.10 * vol_ma20:
                up_score += 1
        up_score = min(5, up_score)

        # ---------- 4) 量价背离 / 卖压衰竭 0–5 ----------
        div_score = 0
        if len(close) >= 11:
            price_now = close.iloc[-1]
            price_5 = close.iloc[-6]
            price_10 = close.iloc[-11]
            obv_now = obv.iloc[-1]
            obv_5 = obv.iloc[-6]
            obv_10 = obv.iloc[-11]

            # 价格继续走弱，但OBV抬高
            if price_now < price_5 and obv_now > obv_5:
                div_score += 3
            elif price_now <= price_5 and obv_now >= obv_5:
                div_score += 2

            if price_now < price_10 and obv_now > obv_10:
                div_score += 1

        # 最近5日平均量低于前5日，且价格仍处于下跌段：卖压衰竭
        if len(volume) >= 11:
            v_recent5 = volume.iloc[-5:].mean()
            v_prev5 = volume.iloc[-10:-5].mean()
            ret5_now = pct_return(close, 5)
            if (
                not pd.isna(ret5_now) and ret5_now < 0
                and v_prev5 > 0 and v_recent5 <= 0.85 * v_prev5
            ):
                div_score += 1
        div_score = min(5, div_score)

        total = int(obv_score + down_score + up_score + div_score)

        reasons = []
        if obv_score:
            reasons.append(f"OBV改善+{obv_score}")
        if down_score:
            reasons.append(f"下跌缩量+{down_score}")
        if up_score:
            reasons.append(f"上涨放量+{up_score}")
        if div_score:
            reasons.append(f"量价背离/卖压衰竭+{div_score}")
        if not reasons:
            reasons.append("暂无明显承接迹象")

        out.update({
            "资金积累总分": total,
            "OBV改善分": obv_score,
            "下跌缩量分": down_score,
            "上涨放量分": up_score,
            "量价背离分": div_score,
            "资金积累解释": "；".join(reasons),
        })
        return out

    except Exception as e:
        out["资金积累解释"] = f"计算失败: {type(e).__name__}"
        return out


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
    """
    Supabase/本地数据 已完全移除。
    当前核心选股只需要 ticker + Supabase 日线。
    公司名/行业/市值若本地没有元数据，则返回安全默认值。
    """
    return str(ticker).upper(), "Unknown", np.nan

# =========================================================
# FUNDAMENTAL CONFIRMATION — V4.3A.3
# Does NOT change Early V2 Score. It confirms company quality and risk.
# =========================================================
@st.cache_data(ttl=21600)
def get_fundamental_confirmation(ticker):
    """
    Supabase/本地数据 基本面数据源已移除。
    此模块不参与当前 KD/RSI 核心选股，因此返回“数据不足”，
    不作为买入/卖出过滤条件。
    """
    return {
        "Fundamental Confirmation": "数据不足",
        "Fundamental Score": np.nan,
        "Quality Check": "数据不足",
        "Valuation Check": "数据不足",
        "Growth Check": "数据不足",
        "ROE": np.nan,
        "Operating Margin": np.nan,
        "Profit Margin": np.nan,
        "Free Cash Flow": np.nan,
        "Operating Cash Flow": np.nan,
        "Debt to Equity": np.nan,
        "Forward PE": np.nan,
        "PEG": np.nan,
        "EV/EBITDA": np.nan,
        "Revenue Growth": np.nan,
        "Earnings Growth": np.nan,
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
    """
    Supabase/本地数据 新闻接口已移除。
    催化模块不参与当前 KD/RSI 核心买入条件。
    """
    return 0, "未启用新闻数据", [], [], []

# =========================================================
# BENCHMARKS + MODULE 4 LEADERSHIP (MAX 20)
# =========================================================
@st.cache_data(ttl=1800)
def get_benchmark_returns():
    # Production RS benchmark data now comes from the same Supabase daily source
    # as the 110-stock A universe, preventing mixed daily-price providers.
    data = supabase_batch_download(tuple(BENCHMARK_TICKERS))
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
# FINAL ROOM QUALITY — PRIORITY LABEL ONLY
# Does NOT change FIX3 买/不买 decision.
# =========================================================
def calc_room_quality(row):
    """Classify upside room for B/C monitoring priority without changing A5 decision."""
    decision = str(row.get("A5决策", ""))
    position = str(row.get("位置判断", ""))
    room = safe_num(row.get("上方空间", np.nan))

    if position == "压力过近":
        return "⛔ 压力过近", 0
    if position == "上方开放" or pd.isna(room):
        return "🌤 上方开放", 2
    if room >= 0.08:
        return "🔥 强空间 ≥8%", 4
    if room >= 0.05:
        return "✅ 良好空间 5–8%", 3
    if room >= 0.02:
        return "🟡 一般空间 2–5%", 2
    if room >= 0:
        return "⚠️ 空间偏小 <2%", 1
    return "⚪ 已越过参考压力", 1

# =========================================================
# PER-STOCK ANALYSIS
# =========================================================

def calc_panic_release_label(df):
    """
    恐慌释放：只做A候选排序和解释，不做硬过滤。

    4个简单特征，每项1分：
      1) 近10日下跌日平均成交量 / 20日均量 >= 1.20
      2) OBV近5日下降
      3) 前5日跌幅 <= -5%
      4) 金叉日成交量 / 20日均量 >= 1.20

    3-4分 = 强
    2分   = 中
    0-1分 = 弱
    """
    out = {"恐慌释放分": 0, "恐慌释放强弱": "弱", "恐慌释放解释": ""}
    try:
        d = _norm_daily_index(df).copy()
        if len(d) < 25:
            out["恐慌释放解释"] = "历史不足25日"
            return out

        close = pd.to_numeric(d["Close"], errors="coerce")
        volume = pd.to_numeric(d["Volume"], errors="coerce")
        ret1 = close.pct_change()
        vol_ma20 = volume.rolling(20).mean().iloc[-1]

        score = 0
        reasons = []

        # 1. 下跌日放量
        recent = pd.DataFrame({"ret": ret1, "vol": volume}).tail(10)
        down = recent[recent["ret"] < 0]
        if len(down) >= 2 and pd.notna(vol_ma20) and vol_ma20 > 0:
            ratio = down["vol"].mean() / vol_ma20
            if ratio >= 1.20:
                score += 1
                reasons.append(f"下跌日放量 {ratio:.2f}x")

        # 2. OBV近5日走弱
        direction = np.sign(close.diff()).fillna(0)
        obv = (direction * volume.fillna(0)).cumsum()
        if len(obv) >= 6 and obv.iloc[-1] < obv.iloc[-6]:
            score += 1
            reasons.append("OBV近5日走弱")

        # 3. 前5日明显超跌
        ret5 = pct_return(close, 5)
        if pd.notna(ret5) and ret5 <= -5.0:
            score += 1
            reasons.append(f"前5日跌 {abs(ret5):.1f}%")

        # 4. 金叉日放量
        if pd.notna(vol_ma20) and vol_ma20 > 0:
            vr = volume.iloc[-1] / vol_ma20
            if vr >= 1.20:
                score += 1
                reasons.append(f"金叉日量比 {vr:.2f}x")

        label = "强" if score >= 3 else ("中" if score == 2 else "弱")
        out["恐慌释放分"] = int(score)
        out["恐慌释放强弱"] = label
        out["恐慌释放解释"] = "；".join(reasons) if reasons else "无明显恐慌释放特征"
        return out
    except Exception as e:
        out["恐慌释放解释"] = f"计算失败：{type(e).__name__}"
        return out



def analyze_daily_candidate(ticker, df, benchmarks):
    try:
        if df is None or len(df) < 210:
            return None
        df = df.copy()
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["High", "Low", "Close", "Volume"])
        if len(df) < 50:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        price = float(close.iloc[-1])
        atr14 = safe_num(calc_atr(high, low, close, 14).iloc[-1])
        atr_pct = (atr14 / price) if (price and not pd.isna(atr14)) else np.nan
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
            "ATR%": atr_pct,
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

        # 可解释资金积累评分：正式页面展示/研究使用
        accumulation_detail = calc_explainable_accumulation(df)
        row.update(accumulation_detail)

        # 恐慌释放只用于排序/解释，不会减少候选数量
        row.update(calc_panic_release_label(df))

        # =====================================================
        # CMS A NEW CORE — validated tiering
        # Fixed trigger: strict KD20 golden cross.
        # Preferred filter: prior 5D return <= -3% and ATR% >= 4%.
        # Strong rebound: prior 5D return <= -5% and ATR% >= 4%.
        # RSI / volume / OBV remain monitoring fields only.
        # =====================================================
        kd20_now = (row.get("KD低位金叉20") == "是")
        ret5_now = safe_num(row.get("5D Return", np.nan))
        atr_pct_now = safe_num(row.get("ATR%", np.nan))

        # Locked current-A eligibility/tiering lives in one small module.
        # This is a behavior-preserving extraction of the exact rules above.
        row.update(classify_current_a(kd20_now, ret5_now, atr_pct_now))

        # Early Engine V2：保留，但只负责同等级候选的二次排序。
        # 不再作为是否进入 A 的硬过滤条件。
        row["二次排名总分"] = safe_num(row.get("Early V2 Score", np.nan))
        row["市场结构分"] = safe_num(row.get("Structure Score", np.nan))
        row["趋势动量分"] = safe_num(row.get("Trend & Momentum Score", np.nan))
        row["资金积累分"] = safe_num(row.get("Accumulation Score", np.nan))
        row["领导力分"] = safe_num(row.get("Leadership Score", np.nan))
        row["催化剂分"] = safe_num(row.get("Catalyst Score", np.nan))

        # A6 V3 research fields: calculated strictly as-of the replay date.



        # FINAL priority is ranking information only.





        row["次日决策"] = daily_candidate_status(row) if (ok and q_status == "✅ 通过") else ("🟡 观察候选" if ok and q_status == "⚠️ 观察" else f"⚪ 暂缓：{q_reason}")
        row["Confidence"] = final_confidence(row)
        return row
    except Exception as exc:
        print("[A_ANALYZE_ERROR] " + str(ticker) + ": " + type(exc).__name__ + ": " + str(exc), flush=True)
        return None


# =========================================================
# A6 FINAL — PRIORITY LAYER
# Core decides candidate eligibility; Pivot/Room only ranks candidates.
# =========================================================
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
    "Ticker", "Company", "Rank",
    "A候选等级", "A正式候选", "A动作", "A核心原因",
    "恐慌释放强弱", "恐慌释放分", "恐慌释放解释",
    "APEX近期回撤%", "APEX止跌确认", "APEX放量转强", "APEX量比20",
    "A5决策", "空间等级", "空间优先级",
    "次日决策", "Early V2 Score", "Confidence",
    "Fundamental Confirmation", "Price", "结构阶段", "质量检查",
    "共振数", "MACD共振", "KDJ共振", "RSI共振", "量价共振", "RS共振", "空间共振",
    "位置判断", "A5.2R支撑区", "A5.2R压力区", "距支撑区", "上方空间",
    "Major Resistance Zone", "Major Support Zone", "Short-term Breakout",
    "Structure Score", "Trend & Momentum Score", "Accumulation Score",
    "Leadership Score", "Catalyst Score", "Catalyst Label",
]



@st.cache_data(ttl=120, show_spinner=False)
def load_saved_candidates():
    """读取最近一次已写入 Google Sheet 的 A 候选，页面打开即可看到结果。"""
    try:
        ws = get_daily_worksheet()
        rows = ws.get_all_records()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120, show_spinner=False)
def load_sheet_tab(tab_name):
    """读取同一 Google Sheet 中的指定结果页。"""
    try:
        if gspread is None or Credentials is None:
            return pd.DataFrame()
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
        book = gspread.authorize(creds).open(st.secrets["tracker"]["sheet_name"])
        rows = book.worksheet(tab_name).get_all_records()
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception:
        return pd.DataFrame()



def render_three_systems():
    """首页只读取同一个 Google Sheet 的三张结果表；不运行任何选股。"""
    st.subheader("📋 三套选股结果")
    today = datetime.now().strftime("%Y-%m-%d")

    def show_latest(tab, title, date_col, cols, rename):
        st.markdown(title)
        d = load_sheet_tab(tab)
        if d.empty:
            st.caption("暂无已保存结果")
            return
        latest = ""
        if date_col in d.columns:
            dates = d[date_col].astype(str).str[:10]
            valid = dates[dates.str.strip().ne("")]
            if not valid.empty:
                latest = valid.max()
                d = d[dates.eq(latest)].copy()
        if latest:
            st.caption(("今日结果 · " if latest == today else "最近结果 · ") + latest)
        use = [c for c in cols if c in d.columns]
        if use:
            st.dataframe(d[use].rename(columns=rename).head(10), hide_index=True, use_container_width=True)
        else:
            st.caption("结果表字段暂不可识别")

    show_latest("A_Candidates","#### 🟢 CMS/CRM","最后数据日期",
                ["Ticker","Price","A候选等级"],
                {"Ticker":"股票","Price":"价格","A候选等级":"信号"})
    show_latest("Q_Candidates","#### 🔵 Quant","记录日期",
                ["股票","收盘价","交易说明"],{})
    show_latest("M_Candidates","#### 🟠 MarketBeat","记录日期",
                ["股票","当前价","信号","目标价","潜在空间"],{})


def save_daily_candidates(df):
    """
    安全写入 A_Candidates：
    1) 本次0只候选 -> 不清空旧数据，只提示无候选
    2) 有候选 -> 覆盖写入最新结果
    3) 自动增加“扫描日期”列，方便确认使用的是哪天数据
    """
    if df is None or len(df) == 0:
        return {
            "written": False,
            "count": 0,
            "message": "本次无候选，A_Candidates 保留原数据，未清空。"
        }

    out = df.copy()

    # 最后数据日期：必须尽量使用行情本身的最新交易日，
    # 不能用今天日期冒充市场数据日期。
    last_data_date = ""
    for c in ["最后数据日期", "Date", "date", "交易日期", "日期", "最新日期", "data_date"]:
        if c in out.columns:
            try:
                vals = pd.to_datetime(out[c], errors="coerce").dropna()
                if len(vals):
                    last_data_date = vals.max().strftime("%Y-%m-%d")
                    break
            except Exception:
                pass

    # 候选结果通常来自同一个正式扫描日；若已有 scan_date 字段也尝试读取。
    if not last_data_date and "scan_date" in out.columns:
        try:
            vals = pd.to_datetime(out["scan_date"], errors="coerce").dropna()
            if len(vals):
                last_data_date = vals.max().strftime("%Y-%m-%d")
        except Exception:
            pass

    # 识别不到时明确写“未知”，绝不写当前日期造成误解。
    if not last_data_date:
        last_data_date = "未知"

    # 放在第一列，一打开 Google Sheet 就能看到数据到底更新到哪一天。
    if "最后数据日期" in out.columns:
        out["最后数据日期"] = last_data_date
    else:
        out.insert(0, "最后数据日期", last_data_date)

    # 删除旧版容易混淆的“扫描日期”
    if "扫描日期" in out.columns:
        out = out.drop(columns=["扫描日期"])

    ws = get_daily_worksheet()

    # 只有在有候选时才清空并覆盖
    ws.clear()

    clean = out.copy()
    clean = clean.replace([np.inf, -np.inf], np.nan)
    clean = clean.where(pd.notna(clean), "")

    values = [clean.columns.tolist()] + clean.astype(object).values.tolist()
    ws.update(values=values, range_name="A1")

    return {
        "written": True,
        "count": len(out),
        "message": f"已写入 A_Candidates（{len(out)}只），最后数据日期 {last_data_date}"
    }



# =========================================================
# PRODUCTION UI — lightweight mobile-first dashboard
# =========================================================
with st.expander("🔄 重新运行扫描", expanded=False):
    scan_clicked = st.button("运行今日扫描", type="primary", use_container_width=True)

if scan_clicked:
    try:
        tickers = get_universe()
    except Exception as e:
        st.error(str(e))
        st.stop()

    progress = st.progress(0)
    status = st.empty()

    status.write("正在从 Supabase 读取约1年复权日K数据……")
    try:
        data = supabase_batch_download(tuple(tickers))
        benchmarks = get_benchmark_returns()
        missing_bench = [t for t in BENCHMARK_TICKERS if t not in benchmarks]
        if missing_bench:
            st.error(
                "Supabase 缺少复权基准/板块ETF数据：" + ", ".join(missing_bench) +
                "。RS模块需要与个股使用同一复权口径，本次扫描已停止。"
            )
            st.stop()
    except Exception as e:
        st.error(f"Supabase 复权日K读取失败：{e}")
        st.stop()

    missing_daily = [t for t in tickers if t not in data or data[t] is None or data[t].empty]
    available_tickers = [t for t in tickers if t in data and data[t] is not None and not data[t].empty]

    c_pool1, c_pool2, c_pool3 = st.columns(3)
    c_pool1.metric("目标股票池", len(tickers))
    c_pool2.metric("Supabase可扫描", len(available_tickers))
    c_pool3.metric("暂缺日K", len(missing_daily))

    if missing_daily:
        preview = ", ".join(missing_daily[:30])
        more = f" ……另有 {len(missing_daily)-30} 只" if len(missing_daily) > 30 else ""
        st.warning(
            "股票池已经扩大，但以下股票目前 Supabase 还没有复权日K，因此本次先跳过："
            + preview + more +
            "。KD 20/80 正式扫描不会改用 Supabase/本地数据 日K混跑。"
        )

    if not available_tickers:
        st.error("Supabase 当前没有可用于 KD 20/80 的股票日K，扫描停止。")
        st.stop()

    results = []
    for i, ticker in enumerate(available_tickers, start=1):
        status.write(f"正在分析 {ticker}（{i}/{len(available_tickers)}）")
        # Production scan intentionally does not fall back to Supabase/本地数据 daily OHLCV.
        # Missing Supabase data is skipped so the daily-price provider stays consistent.
        df = data.get(ticker)
        row = analyze_daily_candidate(ticker, df, benchmarks)
        if row is not None:
            results.append(row)
        progress.progress(int(i / len(available_tickers) * 100))

    status.empty()
    if not results:
        st.error("扫描没有得到有效结果，请稍后再试。")
        st.stop()

    all_df = pd.DataFrame(results)
    # CMS A 核心扫描：
    # 先保留全部严格 KD20 金叉信号，便于观察；
    # 再按经过长窗口验证的 A 候选等级排序。
    # 正式优选 = KD20 + 前5日跌>=3% + ATR%>=4%
    # 强反弹 = KD20 + 前5日跌>=5% + ATR%>=4%
    eligible = all_df[
        (pd.to_numeric(all_df["Price"], errors="coerce") >= 5)
        & (pd.to_numeric(all_df["Dollar Volume"], errors="coerce") >= 20_000_000)
        & (all_df["KD低位金叉20"] == "是")
    ].copy()

    eligible["_A优先级"] = pd.to_numeric(
        eligible.get("A优先级", 9), errors="coerce"
    ).fillna(9)
    eligible["_跌幅排序"] = pd.to_numeric(
        eligible.get("5D Return"), errors="coerce"
    )
    eligible["_ATR排序"] = pd.to_numeric(
        eligible.get("ATR%"), errors="coerce"
    )
    eligible["_成交额排序"] = pd.to_numeric(
        eligible.get("Dollar Volume"), errors="coerce"
    )

    eligible["_恐慌排序"] = pd.to_numeric(
        eligible.get("恐慌释放分"), errors="coerce"
    ).fillna(-1)

    # A硬条件不变；恐慌释放只负责同等级排序，不删除股票。
    eligible = eligible.sort_values(
        ["_A优先级", "_恐慌排序", "_跌幅排序", "_ATR排序", "_成交额排序"],
        ascending=[True, False, True, False, False],
    ).drop(
        columns=[
            "_A优先级", "_恐慌排序",
            "_跌幅排序", "_ATR排序", "_成交额排序"
        ],
        errors="ignore"
    ).reset_index(drop=True)

    eligible["Rank"] = eligible.index + 1

    # Google Sheet 导出：只写入当前A候选，不改变选股逻辑
    if st.button("📤 写入 Google Sheet", key="write_sheet_v4"):
        try:
            result = save_daily_candidates(eligible)
            if result.get("written"):
                st.success(result.get("message"))
            else:
                st.warning(result.get("message"))
        except Exception as e:
            st.error(f"写入 Google Sheet 失败：{e}")

    # KD 信号有几只就显示几只，不强制凑数，也不因 top_n 截断。
    top_df = eligible.copy()

    # Keep the latest result during Streamlit reruns.
    st.session_state["v43a_top_df"] = top_df.copy()
    st.session_state["v43a_all_df"] = all_df.copy()
    st.session_state["v43a_scan_date"] = datetime.now().strftime("%Y-%m-%d")


def render_results(top_df, all_df):
    if top_df is None or top_df.empty:
        st.warning("今天没有出现买入候选。")
        sells = pd.DataFrame()
        if all_df is not None and not all_df.empty and "KD高位死叉80" in all_df.columns:
            sells = all_df[all_df["KD高位死叉80"].eq("是")].copy()
        if not sells.empty:
            st.subheader("🔴 卖出检查")
            cols = [c for c in ["Ticker", "Price", "KDJ_K", "KDJ_D"] if c in sells.columns]
            st.dataframe(
                sells[cols].rename(columns={"Ticker":"股票","Price":"价格","KDJ_K":"K","KDJ_D":"D"}),
                hide_index=True, use_container_width=True
            )
        return

    formal = top_df[top_df.get("A正式候选", pd.Series(index=top_df.index, dtype=str)).eq("是")].copy()
    strong = top_df[top_df.get("A候选等级", pd.Series(index=top_df.index, dtype=str)).eq("🔥 强反弹候选")].copy()

    c1, c2, c3 = st.columns(3)
    c1.metric("今日候选", len(top_df))
    c2.metric("正式优选", len(formal))
    c3.metric("强反弹", len(strong))

    st.subheader("⭐ 今日重点")
    focus = formal if not formal.empty else top_df
    focus = focus.head(5).copy()
    cols = [c for c in ["Ticker","Price","A候选等级","5D Return","ATR%","恐慌释放强弱"] if c in focus.columns]
    show = focus[cols].rename(columns={
        "Ticker":"股票", "Price":"价格", "A候选等级":"等级",
        "5D Return":"前5日", "ATR%":"ATR", "恐慌释放强弱":"恐慌释放"
    })
    fmt = {}
    if "价格" in show.columns: fmt["价格"] = "{:.2f}"
    if "前5日" in show.columns: fmt["前5日"] = "{:+.1%}"
    if "ATR" in show.columns: fmt["ATR"] = "{:.1%}"
    st.dataframe(show.style.format(fmt, na_rep=""), hide_index=True, use_container_width=True)

    with st.expander("查看全部候选"):
        cols = [c for c in ["Rank","Ticker","Price","A候选等级","A核心原因","5D Return","ATR%"] if c in top_df.columns]
        show_all = top_df[cols].rename(columns={
            "Rank":"排名","Ticker":"股票","Price":"价格","A候选等级":"等级",
            "A核心原因":"原因","5D Return":"前5日","ATR%":"ATR"
        })
        st.dataframe(show_all, hide_index=True, use_container_width=True)

    if all_df is not None and not all_df.empty and "KD高位死叉80" in all_df.columns:
        sells = all_df[all_df["KD高位死叉80"].eq("是")].copy()
        if not sells.empty:
            st.subheader("🔴 卖出检查")
            cols = [c for c in ["Ticker","Price","KDJ_K","KDJ_D","KD交易动作"] if c in sells.columns]
            st.dataframe(
                sells[cols].rename(columns={"Ticker":"股票","Price":"价格","KDJ_K":"K","KDJ_D":"D","KD交易动作":"动作"}),
                hide_index=True, use_container_width=True
            )


render_three_systems()

st.divider()

if "v43a_top_df" in st.session_state and "v43a_all_df" in st.session_state:
    render_results(st.session_state["v43a_top_df"], st.session_state["v43a_all_df"])
else:
    st.caption("点击上方按钮运行 CMS A：KD20 + 前5日跌幅 + ATR% 扫描。")

