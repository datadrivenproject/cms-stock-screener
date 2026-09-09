import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import io
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
st.set_page_config(page_title="CMS Stock Screener A6 FINAL", page_icon="📈", layout="wide")

st.title("📈 CMS Stock Screener A6 FINAL")
st.caption(
    "盘后正式候选：V2B Core（共振≥4/5 + MACD必过 + 量价必过）。"
    "Pivot / Room 只用于候选优先级；盘中真正买点和退出由 B/C 负责。"
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
# UNIVERSE — A6 FINAL 500 POOL
# =========================================================
# 保留原来的自选成长/热门股，同时自动加入 S&P 500。
# S&P 500 成分会变化，因此不在程序里硬编码 500 个代码。
# 若网络临时无法读取成分表，会自动退回原自选池，不影响 App 启动。
CORE_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX", "ORCL", "IBM", "DELL", "HPE", "SMCI",
    "CRM", "ADBE", "NOW", "PLTR", "PATH", "CRWD", "PANW", "FTNT", "DDOG", "NET", "SNOW", "MDB", "ZS", "OKTA", "TEAM",
    "QCOM", "MU", "INTC", "ARM", "MRVL", "AMAT", "LRCX", "KLAC", "ON", "MCHP",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "PYPL", "COIN", "HOOD", "SOFI", "XYZ", "NU", "IBKR",
    "LLY", "UNH", "ABBV", "MRK", "AMGN", "JNJ", "PFE", "GILD", "ISRG", "TMO", "TEM", "VEEV", "REGN", "VRTX", "DXCM",
    "XOM", "CVX", "COP", "CAT", "GE", "BA", "RTX", "LMT", "ETN", "VRT", "PLUG", "FCX", "SLB", "FSLR", "CEG",
    "WMT", "COST", "HD", "DIS", "UBER", "ABNB", "DASH", "BKNG", "SHOP", "MELI", "RBLX", "SPOT", "ROKU", "DUOL", "RDDT",
    "CRCL", "APP", "RKLB", "ASTS", "IONQ", "RGTI", "SOUN", "HIMS", "CAVA", "CVNA"
]

@st.cache_data(ttl=21600, show_spinner=False)
def get_sp500_tickers():
    """
    A6 FINAL 500池：
    优先从 GitHub Raw 读取当前 S&P 500 成分。
    不再依赖 pd.read_html(Wikipedia)，避免 Streamlit Cloud 上网页表格读取失败。
    """
    sources = [
        "https://raw.githubusercontent.com/chinobing/historical_sp500_constituents/refs/heads/main/sp500_constituents.csv",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    ]

    for url in sources:
        try:
            r = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 CMS-A6-FINAL"}
            )
            if not r.ok or not r.text.strip():
                continue

            df = pd.read_csv(io.StringIO(r.text))
            symbol_col = None
            for c in df.columns:
                if str(c).strip().lower() in {"symbol", "ticker", "tickers"}:
                    symbol_col = c
                    break
            if symbol_col is None:
                continue

            tickers = (
                df[symbol_col]
                .astype(str)
                .str.upper()
                .str.strip()
                .str.replace(".", "-", regex=False)
                .tolist()
            )
            tickers = list(dict.fromkeys(
                t for t in tickers
                if t and t != "NAN"
            ))

            # S&P 500 usually has just over 500 listed securities because of share classes.
            # Fewer than 450 means the source was not read correctly; do not silently fall back to 110.
            if len(tickers) >= 450:
                return tickers
        except Exception:
            continue

    return []

def get_universe():
    sp500 = get_sp500_tickers()

    # Important: do not silently pretend the 110-stock fallback is a 500-stock pool.
    if len(sp500) < 450:
        raise RuntimeError(
            "未能读取 S&P 500 股票名单。A6 FINAL 已停止本次扫描，"
            "不会自动退回原110只股票池。请稍后重试或检查 Streamlit Cloud 网络访问。"
        )

    # 当前 S&P500 + 原自选成长/热门股，去重。
    # 所以目标池通常会略高于500，而不是固定正好500。
    combined = list(dict.fromkeys(sp500 + CORE_UNIVERSE))
    return combined
    # S&P500 + 原自选池，去重。这样不会因为扩池把 PATH/TEM/RKLB 等原来关注股删掉。
    combined = list(dict.fromkeys(sp500 + CORE_UNIVERSE))
    return combined if combined else CORE_UNIVERSE.copy()

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
def supabase_download_single(ticker):
    return supabase_batch_download((str(ticker).upper(),)).get(str(ticker).upper())

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
    macd_ok = bool(
        (macd.iloc[-1] > sig.iloc[-1]) and
        (hist.iloc[-1] > 0) and
        ((hist.iloc[-1] > hist.iloc[-2]) or (hist.iloc[-2] > hist.iloc[-3]))
    )

    # ---------- 势：KDJ (9,3,3) ----------
    ll9 = low.rolling(9).min()
    hh9 = high.rolling(9).max()
    rsv = (close - ll9) / (hh9 - ll9).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    k0, d0, j0 = safe_num(k.iloc[-1]), safe_num(d.iloc[-1]), safe_num(j.iloc[-1])
    kdj_ok = bool((k0 > d0) and (k0 >= 45) and (j0 <= 110))

    # ---------- 势：RSI ----------
    rsi_series = calc_rsi(close, 14)
    rsi = safe_num(rsi_series.iloc[-1])
    rsi_prev = safe_num(rsi_series.iloc[-3])
    rsi_ok = bool((50 <= rsi <= 72) and (rsi >= rsi_prev))

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

    # A6 FINAL / V2B Core:
    # ≥4 of 5 confirmations + MACD mandatory + Volume-Price mandatory.
    # RS remains one of the five confirmations, but can no longer substitute for Volume-Price.
    # Pivot/Room NEVER vetoes a V2B-qualified candidate.
    base_buy = bool(
        resonance_n >= 4
        and macd_ok
        and pv_ok
    )
    decision = "买" if base_buy else "不买"

    if pressure_too_close:
        position_reason = "压力过近"
    elif major_res is None:
        position_reason = "上方开放"
    else:
        position_reason = "空间通过"

    return {
        "A5决策": decision,
        "共振数": resonance_n,
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
        "当日RVOL_A5": rvol,
    }


# =========================================================
# VP1 — VOLUME-PRICE PHASE (TEST LAYER; DOES NOT CHANGE FIX3 DECISION)
# =========================================================
def calc_volume_price_phase(df):
    """Classify volume-price behavior into A/B/C/N using only data available as-of the bar.

    A = 缩量蓄势: healthy dry-up/compression near recent highs.
    B = 放量启动: volume expansion + breakout/strong close; strongest when preceded by dry-up.
    C = 派发/衰竭风险: abnormal volume with stall, upper wick, or heavy down day.
    N = 普通: no clear phase.

    This is a diagnostic/test layer only. It does NOT alter A5.2R FIX3 买/不买.
    """
    out = {
        'VP阶段': 'N 普通', 'VP分': 0, 'VP说明': '暂无明显量价阶段',
        'VP量比20': np.nan, 'VP缩量比': np.nan,
        'VP前期缩量': '否', 'VP放量启动': '否', 'VP派发风险': '否'
    }
    try:
        if df is None or len(df) < 30:
            out['VP说明'] = '数据不足'
            return out
        d = df.copy()
        for c in ['Open','High','Low','Close','Volume']:
            d[c] = pd.to_numeric(d[c], errors='coerce')
        d = d.dropna(subset=['Open','High','Low','Close','Volume'])
        if len(d) < 30:
            out['VP说明'] = '有效数据不足'
            return out

        o,h,l,c,v = d['Open'],d['High'],d['Low'],d['Close'],d['Volume']
        px = float(c.iloc[-1]); prev = float(c.iloc[-2])
        vol20_prev = safe_num(v.iloc[-21:-1].mean())
        vol5_prev = safe_num(v.iloc[-6:-1].mean())
        if not (vol20_prev > 0 and px > 0 and prev > 0):
            out['VP说明'] = '成交量基准不足'
            return out

        rvol = float(v.iloc[-1] / vol20_prev)
        dry_ratio = float(vol5_prev / vol20_prev)
        ret1 = float(px / prev - 1)
        high10_prev = safe_num(h.iloc[-11:-1].max())
        high20_prev = safe_num(h.iloc[-21:-1].max())
        close20_prev = safe_num(c.iloc[-21:-1].max())

        # Recent price compression measured BEFORE current bar, avoiding current breakout contamination.
        pre5h = safe_num(h.iloc[-6:-1].max())
        pre5l = safe_num(l.iloc[-6:-1].min())
        compression5 = (pre5h - pre5l) / px if px > 0 and not pd.isna(pre5h) and not pd.isna(pre5l) else np.nan

        rng = float(h.iloc[-1] - l.iloc[-1])
        if rng > 0:
            close_loc = float((px - l.iloc[-1]) / rng)
            upper_wick = float((h.iloc[-1] - max(o.iloc[-1], px)) / rng)
        else:
            close_loc, upper_wick = 0.5, 0.0

        # Prior dry-up: either the immediate prior 5 bars or the preceding 5-bar block dried up.
        prior_block5 = safe_num(v.iloc[-11:-6].mean())
        prior_block_ratio = prior_block5 / vol20_prev if vol20_prev > 0 and not pd.isna(prior_block5) else np.nan
        prior_dryup = bool(
            dry_ratio <= 0.82 or
            (not pd.isna(prior_block_ratio) and prior_block_ratio <= 0.82)
        )

        near_high = bool(not pd.isna(high20_prev) and px >= high20_prev * 0.88)
        compressed = bool(not pd.isna(compression5) and compression5 <= 0.08)
        accumulation_phase = bool(dry_ratio <= 0.80 and near_high and compressed)

        breakout_price = bool(
            (not pd.isna(high10_prev) and px > high10_prev) or
            (not pd.isna(close20_prev) and px > close20_prev)
        )
        expansion = bool(rvol >= 1.30 and ret1 > 0 and close_loc >= 0.65 and breakout_price)

        huge_volume = rvol >= 1.80
        stall = bool(huge_volume and ret1 < 0.01)
        wick_risk = bool(rvol >= 1.50 and upper_wick >= 0.35)
        heavy_down = bool(rvol >= 1.50 and ret1 <= -0.025)
        distribution = bool(stall or wick_risk or heavy_down)

        if distribution:
            reasons=[]
            if stall: reasons.append('巨量但价格滞涨')
            if wick_risk: reasons.append('放量长上影')
            if heavy_down: reasons.append('放量下跌')
            phase, score, reason = 'C 派发风险', -3, '；'.join(reasons)
        elif expansion:
            if prior_dryup:
                phase, score, reason = 'B 放量启动', 3, '缩量整理后放量突破'
            else:
                phase, score, reason = 'B 放量启动', 2, '放量突破，但前期缩量不明显'
        elif accumulation_phase:
            phase, score, reason = 'A 缩量蓄势', 1, '缩量+波动收窄，等待重新放量'
        else:
            phase, score, reason = 'N 普通', 0, '暂无明显量价阶段'

        out.update({
            'VP阶段': phase, 'VP分': score, 'VP说明': reason,
            'VP量比20': round(rvol, 3), 'VP缩量比': round(dry_ratio, 3),
            'VP前期缩量': '是' if prior_dryup else '否',
            'VP放量启动': '是' if expansion else '否',
            'VP派发风险': '是' if distribution else '否',
        })
        return out
    except Exception:
        out['VP说明'] = '计算异常'
        return out

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
        # A6 V3 research fields: calculated strictly as-of the replay date.
        row.update(calc_v3_pivot_room_fields(df))
        row["空间等级"], row["空间优先级"] = calc_room_quality(row)

        # FINAL priority is ranking information only.
        level, pscore, preason = calc_a6_final_priority(row)
        row["A6优先级"] = level
        row["A6优先分"] = pscore
        row["A6优先原因"] = preason

        row["次日决策"] = daily_candidate_status(row) if (ok and q_status == "✅ 通过") else ("🟡 观察候选" if ok and q_status == "⚠️ 观察" else f"⚪ 暂缓：{q_reason}")
        row["Confidence"] = final_confidence(row)
        return row
    except Exception:
        return None


# =========================================================
# A6 FINAL — PRIORITY LAYER
# Core decides candidate eligibility; Pivot/Room only ranks candidates.
# =========================================================
def calc_a6_final_priority(row):
    score = 0
    reasons = []

    br = str(row.get("Breakout Room Status V3", ""))
    fr = str(row.get("First Room Status V3", ""))
    ps = str(row.get("Pivot Status V3", ""))

    # Strongest validated research signal.
    if br == "Room ≥8%":
        score += 4
        reasons.append("Breakout Room≥8%")
    elif br == "Room 5–8%":
        score += 3
        reasons.append("Breakout Room 5–8%")
    elif br == "Room 2–5%":
        score += 1
        reasons.append("Breakout Room 2–5%")

    # Broader stable signal.
    if fr in ["Room ≥8%", "Room 5–8%", "Room 2–5%"]:
        score += 2
        reasons.append("First Room≥2%")

    # Early-position signal.
    if ps == "突破前 >3%":
        score += 2
        reasons.append("Pivot突破前>3%")

    if score >= 6:
        level = "A+ 最高优先"
    elif score >= 4:
        level = "A 高优先"
    elif score >= 2:
        level = "B 正常优先"
    else:
        level = "C 普通跟踪"

    return level, score, "；".join(reasons) if reasons else "V2B通过；无额外Pivot/Room加分"


# =========================================================
# GOOGLE SHEETS — NEW TAB, DOES NOT OVERWRITE V4.2.1 TRACKER
# =========================================================
DAILY_WORKSHEET = "A_Candidates"

A_SHEET_CN_MAP = {'Scan Date': '扫描日期', 'Scan Time': '扫描时间', 'Ticker': '股票代码', 'Company': '公司', 'Sector': '板块', 'Market Cap': '市值', 'Price': '价格', 'ATR14': 'ATR14', 'RVOL': 'RVOL', 'Dollar Volume': '成交额', '5D Return': '5日涨跌幅', '20D Return': '20日涨跌幅', 'Rank': '排名', 'Early V2 Score': 'Early V2总分', 'Confidence': '信心等级', 'Fundamental Confirmation': '基本面确认', 'Fundamental Reason': '基本面依据', 'Quality Fundamental': '质量', 'FCF Fundamental': '现金流', 'Debt Fundamental': '负债', 'Valuation Fundamental': '估值', 'Growth Fundamental': '增长', 'ROE': 'ROE', 'Operating Margin': '营业利润率', 'Free Cash Flow': '自由现金流', 'Operating Cash Flow': '经营现金流', 'Debt to Equity': 'Debt/Equity', 'Forward PE': 'Forward P/E', 'PEG': 'PEG', 'EV/EBITDA': 'EV/EBITDA', 'Revenue Growth': '营收增长', 'Earnings Growth': '盈利增长', 'Structure Score': '市场结构分', 'Trend & Momentum Score': '趋势动量分', 'Accumulation Score': '资金积累分', 'Leadership Score': '相对强势分', 'Catalyst Score': '催化剂分', 'Major Resistance Zone': '主要压力区', 'Resistance Touches': '压力测试次数', 'Resistance Strength': '压力强度', 'Major Support Zone': '主要支撑区', 'Support Touches': '支撑测试次数', 'Short-term Breakout': '短期突破位', 'Distance to Major Resistance': '距主要压力', 'Distance to Short Breakout': '距短期突破', 'Compression Ratio': '压缩比', 'R→S Flip': 'R→S转换', 'R→S Flip Zone': 'R→S回踩区', 'R→S Flip Touches': 'R→S历史测试次数', 'MA20': 'MA20', 'MA50': 'MA50', 'MA200': 'MA200', 'MA20 Slope 5D': 'MA20 5日斜率', 'MACD': 'MACD', 'MACD Signal': 'MACD信号', 'MACD Histogram': 'MACD柱', 'MACD Phase': 'MACD阶段', 'RSI14': 'RSI14', 'Volume Build Ratio': '量能增强比', 'Up/Down Volume Ratio': '涨跌量比', 'OBV Trend': 'OBV趋势', 'OBV Positive Divergence': 'OBV正背离', 'Stock vs SPY 20D': '个股 vs SPY 20日', 'Sector vs SPY 20D': '板块 vs SPY 20日', 'Stock vs Sector 20D': '个股 vs 板块 20日', 'Stock vs SPY 5D': '个股 vs SPY 5日', 'RS Acceleration': 'RS加速度', 'Sector ETF': '板块ETF', 'Catalyst Label': '催化剂状态', 'Positive Catalyst': '正面催化剂', 'Negative Catalyst': '负面催化剂', 'Headlines': '相关新闻', 'Hard Filter': '硬筛选', 'Hard Filter Reason': '硬筛选原因', 'CMS Context': 'CMS参考', 'VP阶段':'量价阶段', 'VP分':'量价分', 'VP说明':'量价说明', 'VP量比20':'量比20', 'VP缩量比':'缩量比', 'VP前期缩量':'前期缩量', 'VP放量启动':'放量启动', 'VP派发风险':'派发风险'}
A_SHEET_CN_MAP.update({
    '空间等级':'空间等级', '空间优先级':'空间优先级',
    'A6优先级':'A6优先级', 'A6优先分':'A6优先分', 'A6优先原因':'A6优先原因',
    'Pivot Status V3':'Pivot状态', 'First Room Status V3':'First Room',
    'Breakout Room Status V3':'Breakout Room'
})

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
    "Ticker", "Company", "Rank", "A5决策", "空间等级", "空间优先级",
    "次日决策", "Early V2 Score", "Confidence",
    "Fundamental Confirmation", "Price", "结构阶段", "质量检查",
    "共振数", "MACD共振", "KDJ共振", "RSI共振", "量价共振", "RS共振", "空间共振",
    "位置判断", "A5.2R支撑区", "A5.2R压力区", "距支撑区", "上方空间",
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
# A STRONG-STOCK HISTORY / BACKTEST — V4.3A.3B-FIX3
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



def calc_v3_pivot_room_fields(df):
    """A6 V3.1 Research: as-of-date Pivot / First Room / Breakout Room fields.

    Research only — never changes LIVE A selection.

    Definitions
    -----------
    Pivot:
        Prior 20-session high (current bar excluded).
    Pivot Status:
        按当前收盘价相对 Pivot 的位置分层：
        - 突破前 >3%
        - 接近Pivot 0–3%
        - 刚突破 0–2%
        - 突破后延伸 >2%
    First Room:
        从当前价到“第一个上方障碍”的空间。
        第一个障碍取 Pivot 与有效重复压力区中距离当前价最近者。
        若没有上方障碍，则记为 NaN，并标记“开放”。
    Breakout Room:
        从 Pivot 到 Pivot 上方下一处有效重复压力区的空间。
        这回答“如果突破当前 Pivot，突破后还有多少路可走”。
        如果 Pivot 上方没有明确重复压力，则记为 NaN，并标记“开放”。

    所有结构只使用截至当日已经出现的 OHLCV；不使用未来数据。
    """
    out = {
        "Pivot Price V3": np.nan,
        "Pivot Status V3": "数据不足",
        "Pivot Distance V3": np.nan,
        "First Room V3": np.nan,
        "First Room Status V3": "不确定",
        "First Obstacle V3": np.nan,
        "Breakout Room V3": np.nan,
        "Breakout Room Status V3": "不确定",
        "Next Resistance Above Pivot V3": np.nan,
    }
    try:
        if df is None or len(df) < 60:
            return out

        d = df.copy()
        for c in ["High", "Low", "Close"]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=["High", "Low", "Close"])
        if len(d) < 60:
            return out

        price = float(d["Close"].iloc[-1])
        if not np.isfinite(price) or price <= 0:
            return out

        # Pivot = prior 20-session high, excluding today's bar.
        pivot = safe_num(d["High"].shift(1).rolling(20).max().iloc[-1])
        if pd.isna(pivot) or pivot <= 0:
            return out

        pivot_dist = (pivot - price) / price
        if pivot_dist > 0.03:
            pivot_status = "突破前 >3%"
        elif 0 <= pivot_dist <= 0.03:
            pivot_status = "接近Pivot 0–3%"
        else:
            ext = (price - pivot) / pivot
            if ext <= 0.02:
                pivot_status = "刚突破 0–2%"
            else:
                pivot_status = "突破后延伸 >2%"

        # Rebuild repeated swing-high resistance zones using only as-of-date data.
        hist = d.tail(252).copy()
        high = hist["High"]
        core_high = high.iloc[:-3] if len(high) > 20 else high
        swing_highs = _swing_points(core_high, side=5, mode="high")

        atr14 = safe_num(calc_atr(hist["High"], hist["Low"], hist["Close"], 14).iloc[-1])
        atr_pct = atr14 / price if price > 0 and not pd.isna(atr14) else 0.015
        tol = float(np.clip(max(0.012, 0.65 * atr_pct), 0.012, 0.025))
        resistance_zones = _cluster_swings(swing_highs, tolerance_pct=tol)

        # Candidate repeated resistance obstacles above current price.
        obstacles = []
        for z in resistance_zones:
            low_edge = safe_num(z.get("low"))
            if not pd.isna(low_edge) and low_edge > price * 1.001:
                obstacles.append(low_edge)

        # Pivot itself is a real first obstacle only while price is below it.
        if pivot > price * 1.001:
            obstacles.append(float(pivot))

        if obstacles:
            first_obstacle = float(min(obstacles))
            first_room = first_obstacle / price - 1.0
            first_status = (
                "Room <2%" if first_room < .02 else
                "Room 2–5%" if first_room < .05 else
                "Room 5–8%" if first_room < .08 else
                "Room ≥8%"
            )
        else:
            first_obstacle = np.nan
            first_room = np.nan
            first_status = "开放"

        # Next repeated resistance strictly above the pivot.
        above_pivot = []
        for z in resistance_zones:
            low_edge = safe_num(z.get("low"))
            if not pd.isna(low_edge) and low_edge > pivot * 1.005:
                above_pivot.append(low_edge)

        if above_pivot:
            next_res = float(min(above_pivot))
            breakout_room = next_res / pivot - 1.0
            breakout_status = (
                "Room <2%" if breakout_room < .02 else
                "Room 2–5%" if breakout_room < .05 else
                "Room 5–8%" if breakout_room < .08 else
                "Room ≥8%"
            )
        else:
            next_res = np.nan
            breakout_room = np.nan
            breakout_status = "开放"

        out.update({
            "Pivot Price V3": float(pivot),
            "Pivot Status V3": pivot_status,
            "Pivot Distance V3": float(pivot_dist),
            "First Room V3": float(first_room) if not pd.isna(first_room) else np.nan,
            "First Room Status V3": first_status,
            "First Obstacle V3": float(first_obstacle) if not pd.isna(first_obstacle) else np.nan,
            "Breakout Room V3": float(breakout_room) if not pd.isna(breakout_room) else np.nan,
            "Breakout Room Status V3": breakout_status,
            "Next Resistance Above Pivot V3": float(next_res) if not pd.isna(next_res) else np.nan,
        })
        return out
    except Exception:
        return out


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

        # A6 V3 FIX1:
        # Historical replay must also generate Pivot / First Room / Breakout Room
        # strictly from data available as of that replay date.
        row.update(calc_v3_pivot_room_fields(df))

        row["空间等级"], row["空间优先级"] = calc_room_quality(row)

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
    try:
        tickers = get_universe()
    except Exception as e:
        if status_box is not None:
            status_box.write(str(e))
        return pd.DataFrame()

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
    """Same-window comparison: A4 vs current A5.2R vs A6 V2B (Volume mandatory)."""
    if bt is None or bt.empty:
        return
    d = bt.copy()
    req = [
        'Replay Date','Ticker','Replay Eligible Rank','5D Max Gain','Hard Filter',
        'A5决策','共振数','Replay Core Score 85','Leadership Score','Accumulation Score',
        'MACD共振','KDJ共振','RSI共振','量价共振','RS共振','空间共振'
    ]
    if any(c not in d.columns for c in req):
        st.warning("当前缓存字段不完整。请重新运行历史回测，生成完整共振字段。")
        return

    d['5D Max Gain'] = pd.to_numeric(d['5D Max Gain'], errors='coerce')
    d['共振数'] = pd.to_numeric(d['共振数'], errors='coerce')
    d = d.dropna(subset=['5D Max Gain'])
    if d.empty:
        return

    # A4 = existing eligible Top10 per replay day.
    a4 = d[d['Replay Eligible Rank'] <= 10].copy()

    # Current A5.2R rule (CONTROL): >=4/5 + MACD + (Volume OR RS), no forced 10.
    pool = d[d['Hard Filter'].eq('通过')].copy()
    pool['_a5_buy'] = (pool['A5决策'] == '买').astype(int)
    pool = pool.sort_values(
        ['Replay Date','_a5_buy','共振数','Replay Core Score 85','Leadership Score','Accumulation Score'],
        ascending=[True,False,False,False,False,False]
    )
    a5 = pool.groupby('Replay Date', group_keys=False).head(10).copy()
    a5 = a5[a5['A5决策'] == '买'].copy()

    # A6 V2B EXPERIMENT: only one change from A5.2R.
    # >=4/5 + MACD mandatory + Volume mandatory. RS remains one of the 5 resonance items,
    # but RS can no longer substitute for failed Volume resonance.
    exp = d[d['Hard Filter'].eq('通过')].copy()
    macd = exp['MACD共振'].eq('是')
    pv = exp['量价共振'].eq('是')
    exp['_v2b_buy'] = ((exp['共振数'] >= 4) & macd & pv).astype(int)
    exp = exp.sort_values(
        ['Replay Date','_v2b_buy','共振数','Replay Core Score 85','Leadership Score','Accumulation Score'],
        ascending=[True,False,False,False,False,False]
    )
    v2b = exp.groupby('Replay Date', group_keys=False).head(10).copy()
    v2b = v2b[v2b['_v2b_buy'] == 1].copy()

    def summary(x, label):
        g = pd.to_numeric(x['5D Max Gain'], errors='coerce').dropna()
        return {
            '版本': label,
            '入选样本': len(g),
            '平均每天': len(g) / max(d['Replay Date'].nunique(), 1),
            '≥3%': (g >= .03).mean() if len(g) else np.nan,
            '≥5%': (g >= .05).mean() if len(g) else np.nan,
            '≥8%': (g >= .08).mean() if len(g) else np.nan,
            '平均5日最大涨幅': g.mean() if len(g) else np.nan,
            '中位数5日最大涨幅': g.median() if len(g) else np.nan,
            '弱股<2%': (g < .02).mean() if len(g) else np.nan,
        }

    comp = pd.DataFrame([
        summary(a4,'当前A4 Top10'),
        summary(a5,'A5.2R 当前规则'),
        summary(v2b,'A6 V2B：量价必须通过')
    ])
    st.header("🧪 60日 A/B：A5.2R 当前规则 vs A6 V2B 量价必过")
    st.caption(
        "唯一实验改动：当前规则 = 共振≥4/5 + MACD必过 +（量价或RS至少一个）；"
        "A6 V2B = 共振≥4/5 + MACD必过 + 量价必过。RS仍保留为5项共振之一。"
        "支撑/压力/Room仍只做位置与风险信息，不参与一票否决。"
    )
    st.dataframe(
        comp.style.format({
            '平均每天':'{:.2f}','≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
            '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
        }, na_rep=''),
        hide_index=True, use_container_width=True
    )

    # Direct delta of V2B versus current A5.2R control.
    if len(a5) and len(v2b):
        c = summary(a5,'control')
        e = summary(v2b,'experiment')
        delta = pd.DataFrame([{
            '对比':'A6 V2B - A5.2R',
            '样本变化': e['入选样本'] - c['入选样本'],
            'Δ平均每天': e['平均每天'] - c['平均每天'],
            'Δ≥3%': e['≥3%'] - c['≥3%'],
            'Δ≥5%': e['≥5%'] - c['≥5%'],
            'Δ≥8%': e['≥8%'] - c['≥8%'],
            'Δ平均5D最大涨幅': e['平均5日最大涨幅'] - c['平均5日最大涨幅'],
            'Δ中位数5D最大涨幅': e['中位数5日最大涨幅'] - c['中位数5日最大涨幅'],
            'Δ弱股<2%': e['弱股<2%'] - c['弱股<2%'],
        }])
        st.subheader("A6 V2B 相对当前 A5.2R 的净变化")
        st.dataframe(
            delta.style.format({
                'Δ平均每天':'{:+.2f}','Δ≥3%':'{:+.1%}','Δ≥5%':'{:+.1%}','Δ≥8%':'{:+.1%}',
                'Δ平均5D最大涨幅':'{:+.2%}','Δ中位数5D最大涨幅':'{:+.2%}','Δ弱股<2%':'{:+.1%}'
            }, na_rep=''), hide_index=True, use_container_width=True
        )

    # Show exactly what V2B removes: names that current A5 buys because RS substitutes for Volume.
    removed = a5[(a5['量价共振'] != '是') & (a5['RS共振'] == '是')].copy()
    if not removed.empty:
        g = pd.to_numeric(removed['5D Max Gain'], errors='coerce').dropna()
        removed_summary = pd.DataFrame([{
            '被V2B剔除的类型':'A5买入但量价=否、RS=是',
            '样本':len(g),
            '≥3%':(g >= .03).mean() if len(g) else np.nan,
            '≥5%':(g >= .05).mean() if len(g) else np.nan,
            '≥8%':(g >= .08).mean() if len(g) else np.nan,
            '平均5D最大涨幅':g.mean() if len(g) else np.nan,
            '弱股<2%':(g < .02).mean() if len(g) else np.nan,
        }])
        st.subheader("V2B 到底剔除了什么")
        st.dataframe(
            removed_summary.style.format({
                '≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
                '平均5D最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
            }, na_rep=''), hide_index=True, use_container_width=True
        )

    # Indicator hit-rate table retained for context.
    rows = []
    for c in ['MACD共振','KDJ共振','RSI共振','量价共振','RS共振','空间共振']:
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
        }, na_rep=''), hide_index=True, use_container_width=True
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


def _vp_summary(x, label):
    g = pd.to_numeric(x.get('5D Max Gain'), errors='coerce').dropna() if isinstance(x, pd.DataFrame) else pd.Series(dtype=float)
    return {
        '版本/阶段': label,
        '样本': len(g),
        '≥3%': (g >= .03).mean() if len(g) else np.nan,
        '≥5%': (g >= .05).mean() if len(g) else np.nan,
        '≥8%': (g >= .08).mean() if len(g) else np.nan,
        '平均5日最大涨幅': g.mean() if len(g) else np.nan,
        '中位数5日最大涨幅': g.median() if len(g) else np.nan,
        '弱股<2%': (g < .02).mean() if len(g) else np.nan,
    }


def _current_fix3_selection_for_vp(d):
    """Rebuild exactly the current A5.2R FIX3 historical selection; no forced 10."""
    pool = d[d['Hard Filter'].eq('通过')].copy()
    pool['_buy'] = (pool['A5决策'] == '买').astype(int)
    pool['共振数'] = pd.to_numeric(pool['共振数'], errors='coerce')
    pool = pool.sort_values(
        ['Replay Date','_buy','共振数','Replay Core Score 85','Leadership Score','Accumulation Score'],
        ascending=[True,False,False,False,False,False]
    )
    out = pool.groupby('Replay Date', group_keys=False).head(10).copy()
    return out[out['A5决策'].eq('买')].copy()


def render_vp1_backtest(bt):
    """VP1 diagnostic backtest. Does not modify FIX3 selection logic."""
    if bt is None or bt.empty:
        return
    d = bt.copy()
    req = ['Replay Date','Ticker','Hard Filter','A5决策','共振数','VP阶段','VP分','VP量比20','5D Max Gain']
    missing = [c for c in req if c not in d.columns]
    if missing:
        st.warning('VP1历史字段尚未生成。请重新点击上方“运行60日 A5.2R + VP1 回测”。')
        return
    d['5D Max Gain'] = pd.to_numeric(d['5D Max Gain'], errors='coerce')
    d = d.dropna(subset=['5D Max Gain'])
    if d.empty:
        return

    st.header('🧪 VP1 — Volume-Price Phase 历史回测')
    st.caption('VP1只做诊断，不改变 A5.2R FIX3 的买/不买。所有阶段均使用当时已知OHLCV计算，再观察随后5个交易日。')

    # Table A: all replay samples by phase — validates whether phases themselves separate outcomes.
    phase_order = ['A 缩量蓄势','B 放量启动','C 派发风险','N 普通']
    rows=[]
    for ph in phase_order:
        rows.append(_vp_summary(d[d['VP阶段'].eq(ph)], ph))
    phase_df=pd.DataFrame(rows)
    st.subheader('① 全历史样本：A / B / C / N 各阶段未来5日表现')
    st.dataframe(phase_df.style.format({
        '≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
        '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    # Table B: only names that FIX3 actually selected. This is the key apples-to-apples diagnostic.
    fix3 = _current_fix3_selection_for_vp(d)
    rows=[]
    for ph in phase_order:
        rows.append(_vp_summary(fix3[fix3['VP阶段'].eq(ph)], f'FIX3买入 + {ph}'))
    fix3_phase=pd.DataFrame(rows)
    st.subheader('② FIX3实际入选样本内部：不同VP阶段表现')
    st.dataframe(fix3_phase.style.format({
        '≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
        '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    # Table C: candidate VP gates vs unchanged benchmark. This does NOT apply them to live selection.
    variants = [
        ('FIX3 原版 Benchmark', fix3),
        ('FIX3 + 仅B放量启动', fix3[fix3['VP阶段'].eq('B 放量启动')]),
        ('FIX3 + A/B健康阶段', fix3[fix3['VP阶段'].isin(['A 缩量蓄势','B 放量启动'])]),
        ('FIX3 + 排除C派发风险', fix3[~fix3['VP阶段'].eq('C 派发风险')]),
    ]
    comp=pd.DataFrame([_vp_summary(x,label) for label,x in variants])
    st.subheader('③ FIX3 Benchmark vs VP候选过滤方式（仅回测，不改正式逻辑）')
    st.dataframe(comp.style.format({
        '≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
        '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    # Transition-like B quality: B preceded by dry-up vs B without clear dry-up.
    if 'VP前期缩量' in fix3.columns:
        b = fix3[fix3['VP阶段'].eq('B 放量启动')]
        trans = pd.DataFrame([
            _vp_summary(b[b['VP前期缩量'].eq('是')], 'B：前期缩量→放量启动'),
            _vp_summary(b[b['VP前期缩量'].ne('是')], 'B：直接放量启动'),
        ])
        st.subheader('④ B阶段细分：真正的“缩量 → 放量启动”是否更强')
        st.dataframe(trans.style.format({
            '≥3%':'{:.1%}','≥5%':'{:.1%}','≥8%':'{:.1%}',
            '平均5日最大涨幅':'{:+.2%}','中位数5日最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
        }, na_rep=''), hide_index=True, use_container_width=True)

    st.info('判断标准：如果 B（尤其“前期缩量→B”）的 ≥5%/≥8% 命中率明显高于 FIX3 Benchmark，同时 C 的弱股率明显更高，VP1 才值得进入下一轮正式规则测试。当前页面不会自动修改 FIX3。')



def _room_summary(x, label):
    """Summary for Pivot/Room research; all future returns are outcome labels only."""
    if not isinstance(x, pd.DataFrame) or x.empty:
        return {
            '版本/空间组': label, '样本': 0,
            '1D平均最大涨幅': np.nan, '3D平均最大涨幅': np.nan,
            '5D≥3%': np.nan, '5D≥5%': np.nan, '5D≥8%': np.nan,
            '5D平均最大涨幅': np.nan, '5D中位数最大涨幅': np.nan,
            '弱股<2%': np.nan,
        }
    g1 = pd.to_numeric(x.get('1D Max Gain'), errors='coerce')
    g3 = pd.to_numeric(x.get('3D Max Gain'), errors='coerce')
    g5 = pd.to_numeric(x.get('5D Max Gain'), errors='coerce')
    valid = g5.notna()
    g5v = g5[valid]
    return {
        '版本/空间组': label,
        '样本': int(valid.sum()),
        '1D平均最大涨幅': g1[valid].mean() if valid.any() else np.nan,
        '3D平均最大涨幅': g3[valid].mean() if valid.any() else np.nan,
        '5D≥3%': (g5v >= .03).mean() if len(g5v) else np.nan,
        '5D≥5%': (g5v >= .05).mean() if len(g5v) else np.nan,
        '5D≥8%': (g5v >= .08).mean() if len(g5v) else np.nan,
        '5D平均最大涨幅': g5v.mean() if len(g5v) else np.nan,
        '5D中位数最大涨幅': g5v.median() if len(g5v) else np.nan,
        '弱股<2%': (g5v < .02).mean() if len(g5v) else np.nan,
    }


def _base_buy_candidates_for_room(d):
    """Reconstruct the core A5.2R buy condition BEFORE the current space veto."""
    x = d[d['Hard Filter'].eq('通过')].copy()
    rn = pd.to_numeric(x.get('共振数'), errors='coerce')
    macd = x.get('MACD共振', pd.Series(index=x.index, dtype=object)).eq('是')
    pv = x.get('量价共振', pd.Series(index=x.index, dtype=object)).eq('是')
    rs = x.get('RS共振', pd.Series(index=x.index, dtype=object)).eq('是')
    x = x[(rn >= 4) & macd & (pv | rs)].copy()
    if x.empty:
        return x
    x['_room_rank'] = pd.to_numeric(x.get('Replay Core Score 85'), errors='coerce')
    x['_rn'] = pd.to_numeric(x.get('共振数'), errors='coerce')
    x = x.sort_values(
        ['Replay Date','_rn','_room_rank','Leadership Score','Accumulation Score'],
        ascending=[True,False,False,False,False]
    )
    # Match the no-force-10 framework while keeping pre-space candidates comparable by day.
    return x.groupby('Replay Date', group_keys=False).head(10).copy()


def _room_bucket(df):
    """Mutually exclusive room buckets using only as-of-date resistance information."""
    if df is None or df.empty:
        return pd.Series(dtype=object)
    room = pd.to_numeric(df.get('上方空间'), errors='coerce')
    pos = df.get('位置判断', pd.Series(index=df.index, dtype=object)).astype(str)
    out = pd.Series('其他/不确定', index=df.index, dtype=object)
    out[pos.eq('上方开放') | room.isna()] = '上方开放'
    out[(room >= .08)] = 'Room ≥8%'
    out[(room >= .05) & (room < .08)] = 'Room 5–8%'
    out[(room >= .02) & (room < .05)] = 'Room 2–5%'
    out[(room >= 0) & (room < .02)] = 'Room <2%'
    out[room < 0] = '已进入/越过压力区'
    return out


def render_pivot_room_backtest(bt):
    """Pivot/Room diagnostic backtest. Does not modify live FIX3 decision logic."""
    if bt is None or bt.empty:
        return
    d = bt.copy()
    req = [
        'Replay Date','Ticker','Hard Filter','A5决策','共振数','MACD共振','量价共振','RS共振',
        '位置判断','上方空间','压力测试次数_A52R','5D Max Gain'
    ]
    missing = [c for c in req if c not in d.columns]
    if missing:
        st.warning('Pivot/Room历史字段尚未完整生成：' + ', '.join(missing))
        return

    for c in ['1D Max Gain','3D Max Gain','5D Max Gain','上方空间','压力测试次数_A52R']:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['5D Max Gain'])
    if d.empty:
        return

    st.header('🧭 Pivot / Room — 压力位与上方空间历史验证')
    st.caption(
        '本模块只做研究，不改变 A5.2R FIX3 正式买/不买。压力区、测试次数和 Room 均只使用回放当日之前的OHLCV计算；'
        '随后1/3/5日涨幅仅作为结果标签。'
    )

    # A. Current FIX3 buys grouped by mutually-exclusive room bucket.
    fix3 = _current_fix3_selection_for_vp(d)
    fix3['Room分组'] = _room_bucket(fix3)
    order = ['上方开放','Room ≥8%','Room 5–8%','Room 2–5%','Room <2%','已进入/越过压力区','其他/不确定']
    rows = []
    for lab in order:
        x = fix3[fix3['Room分组'].eq(lab)]
        if len(x) or lab in ['上方开放','Room ≥8%','Room 5–8%','Room 2–5%','Room <2%']:
            rows.append(_room_summary(x, lab))
    t1 = pd.DataFrame(rows)
    st.subheader('① FIX3实际入选样本：不同上方空间的1D / 3D / 5D表现')
    st.dataframe(t1.style.format({
        '1D平均最大涨幅':'{:+.2%}','3D平均最大涨幅':'{:+.2%}',
        '5D≥3%':'{:.1%}','5D≥5%':'{:.1%}','5D≥8%':'{:.1%}',
        '5D平均最大涨幅':'{:+.2%}','5D中位数最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    # B. Threshold variants against unchanged FIX3 benchmark.
    room = pd.to_numeric(fix3['上方空间'], errors='coerce')
    open_mask = fix3['位置判断'].eq('上方开放') | room.isna()
    variants = [
        ('FIX3 原版 Benchmark', fix3),
        ('FIX3 + 上方开放', fix3[open_mask]),
        ('FIX3 + 开放或Room≥8%', fix3[open_mask | (room >= .08)]),
        ('FIX3 + 开放或Room≥5%', fix3[open_mask | (room >= .05)]),
        ('FIX3 + 开放或Room≥3%', fix3[open_mask | (room >= .03)]),
    ]
    t2 = pd.DataFrame([_room_summary(x, lab) for lab, x in variants])
    st.subheader('② FIX3 Benchmark vs Room候选阈值（仅回测，不改正式逻辑）')
    st.dataframe(t2.style.format({
        '1D平均最大涨幅':'{:+.2%}','3D平均最大涨幅':'{:+.2%}',
        '5D≥3%':'{:.1%}','5D≥5%':'{:.1%}','5D≥8%':'{:.1%}',
        '5D平均最大涨幅':'{:+.2%}','5D中位数最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    # C. Validate the existing pressure-too-close veto on pre-space core-buy candidates.
    base = _base_buy_candidates_for_room(d)
    if not base.empty:
        room_b = pd.to_numeric(base['上方空间'], errors='coerce')
        touches = pd.to_numeric(base['压力测试次数_A52R'], errors='coerce').fillna(0)
        pos_b = base['位置判断'].astype(str)
        close_pressure = pos_b.eq('压力过近') | ((touches >= 2) & (room_b >= 0) & (room_b < .02))
        space_pass = ~close_pressure
        t3 = pd.DataFrame([
            _room_summary(base, 'Core Buy（空间过滤前）'),
            _room_summary(base[space_pass], '当前FIX3：空间通过'),
            _room_summary(base[close_pressure], '当前FIX3：压力过近被否决'),
        ])
        st.subheader('③ 当前“压力过近”否决是否有效')
        st.dataframe(t3.style.format({
            '1D平均最大涨幅':'{:+.2%}','3D平均最大涨幅':'{:+.2%}',
            '5D≥3%':'{:.1%}','5D≥5%':'{:.1%}','5D≥8%':'{:.1%}',
            '5D平均最大涨幅':'{:+.2%}','5D中位数最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
        }, na_rep=''), hide_index=True, use_container_width=True)

        # D. Pivot strength / repeated resistance structure.
        open_b = pos_b.eq('上方开放') | room_b.isna()
        one_touch = (~open_b) & (touches <= 1)
        repeated_far = (~open_b) & (touches >= 2) & (room_b >= .02)
        repeated_close = (~open_b) & (touches >= 2) & (room_b >= 0) & (room_b < .02)
        t4 = pd.DataFrame([
            _room_summary(base[open_b], '无明确上方压力'),
            _room_summary(base[one_touch], '弱压力：≤1次测试'),
            _room_summary(base[repeated_far], '重复压力≥2次，但Room≥2%'),
            _room_summary(base[repeated_close], '重复压力≥2次，且Room<2%'),
        ])
        st.subheader('④ Pivot强度：压力测试次数 × 距离')
        st.dataframe(t4.style.format({
            '1D平均最大涨幅':'{:+.2%}','3D平均最大涨幅':'{:+.2%}',
            '5D≥3%':'{:.1%}','5D≥5%':'{:.1%}','5D≥8%':'{:.1%}',
            '5D平均最大涨幅':'{:+.2%}','5D中位数最大涨幅':'{:+.2%}','弱股<2%':'{:.1%}'
        }, na_rep=''), hide_index=True, use_container_width=True)

    st.info(
        '判断重点：只有当“开放或Room≥5%/8%”在 ≥5%、≥8%、5D平均涨幅和弱股率上形成清晰、稳定的改善，'
        '同时样本量没有被过度砍掉，才考虑把更严格Room阈值并入A。否则继续保留FIX3当前只否决“重复压力且<2%”的规则。'
    )


def _v3_v2b_selection(d):
    """Rebuild exactly the A6 V2B research selection, no forced fill."""
    x = d[d["Hard Filter"].eq("通过")].copy()
    x["共振数"] = pd.to_numeric(x["共振数"], errors="coerce")
    macd = x["MACD共振"].eq("是")
    pv = x["量价共振"].eq("是")
    x["_v2b_buy"] = ((x["共振数"] >= 4) & macd & pv).astype(int)
    x = x.sort_values(
        ["Replay Date", "_v2b_buy", "共振数", "Replay Core Score 85",
         "Leadership Score", "Accumulation Score"],
        ascending=[True, False, False, False, False, False]
    )
    x = x.groupby("Replay Date", group_keys=False).head(10).copy()
    return x[x["_v2b_buy"].eq(1)].copy()


def _v3_summary(x, label, dates_n):
    g = pd.to_numeric(x.get("5D Max Gain"), errors="coerce").dropna()
    return {
        "分层": label,
        "样本": len(g),
        "平均每天": len(g) / max(int(dates_n), 1),
        "≥3%": (g >= .03).mean() if len(g) else np.nan,
        "≥5%": (g >= .05).mean() if len(g) else np.nan,
        "≥8%": (g >= .08).mean() if len(g) else np.nan,
        "平均5D最大涨幅": g.mean() if len(g) else np.nan,
        "中位数5D最大涨幅": g.median() if len(g) else np.nan,
        "弱股<2%": (g < .02).mean() if len(g) else np.nan,
    }


def _render_v3_table(rows):
    t = pd.DataFrame(rows)
    st.dataframe(
        t.style.format({
            "平均每天": "{:.2f}",
            "≥3%": "{:.1%}", "≥5%": "{:.1%}", "≥8%": "{:.1%}",
            "平均5D最大涨幅": "{:+.2%}",
            "中位数5D最大涨幅": "{:+.2%}",
            "弱股<2%": "{:.1%}",
        }, na_rep=""),
        hide_index=True,
        use_container_width=True
    )


def render_a6_v3_pivot_room_research(bt):
    """V2B Core fixed; Pivot/Room fields are stratification only."""
    if bt is None or bt.empty:
        return

    req = [
        "Replay Date", "Hard Filter", "共振数", "MACD共振", "量价共振",
        "Replay Core Score 85", "Leadership Score", "Accumulation Score",
        "5D Max Gain", "Pivot Status V3", "First Room Status V3",
        "Breakout Room Status V3"
    ]
    missing = [c for c in req if c not in bt.columns]
    if missing:
        st.warning("当前缓存还是旧回测结果，尚无A6 V3 Pivot/Room字段。请重新点击“运行60日 A6 V3 Pivot/Room 回测”。缺少：" + ", ".join(missing))
        return

    d = bt.copy()
    d["5D Max Gain"] = pd.to_numeric(d["5D Max Gain"], errors="coerce")
    d = d.dropna(subset=["5D Max Gain"])
    if d.empty:
        return

    v2b = _v3_v2b_selection(d)
    dates_n = d["Replay Date"].nunique()

    st.header("🧭 Pivot / Room 优先级验证")
    st.caption(
        "V2B Core完全不变：共振≥4/5 + MACD必过 + 量价必过；"
        "Pivot Status、First Room、Breakout Room 当前只做60日分层研究，不参与正式买/不买。"
    )

    base = _v3_summary(v2b, "A6 V2B Core Benchmark", dates_n)
    st.subheader("① V2B Benchmark")
    _render_v3_table([base])

    st.subheader("② Pivot Status：突破前 / 接近 / 刚突破 / 延伸")
    pivot_order = ["突破前 >3%", "接近Pivot 0–3%", "刚突破 0–2%", "突破后延伸 >2%", "数据不足"]
    rows = [_v3_summary(v2b[v2b["Pivot Status V3"].eq(lab)], lab, dates_n)
            for lab in pivot_order if (v2b["Pivot Status V3"].eq(lab)).any() or lab != "数据不足"]
    _render_v3_table(rows)

    st.subheader("③ First Room：当前价到第一个上方障碍")
    room_order = ["开放", "Room ≥8%", "Room 5–8%", "Room 2–5%", "Room <2%", "不确定"]
    rows = [_v3_summary(v2b[v2b["First Room Status V3"].eq(lab)], lab, dates_n)
            for lab in room_order if (v2b["First Room Status V3"].eq(lab)).any() or lab != "不确定"]
    _render_v3_table(rows)

    st.subheader("④ Breakout Room：突破Pivot后到下一重复压力区")
    rows = [_v3_summary(v2b[v2b["Breakout Room Status V3"].eq(lab)], lab, dates_n)
            for lab in room_order if (v2b["Breakout Room Status V3"].eq(lab)).any() or lab != "不确定"]
    _render_v3_table(rows)

    # =========================================================
    # A6 V3.1 precise combination research
    # "开放" is deliberately excluded from Room-good definitions.
    # V2B Core remains unchanged; all tests below are research only.
    # =========================================================
    first_ge5 = v2b["First Room Status V3"].isin(["Room ≥8%", "Room 5–8%"])
    first_ge2 = v2b["First Room Status V3"].isin(["Room ≥8%", "Room 5–8%", "Room 2–5%"])
    breakout_ge8 = v2b["Breakout Room Status V3"].eq("Room ≥8%")
    breakout_ge5 = v2b["Breakout Room Status V3"].isin(["Room ≥8%", "Room 5–8%"])
    pivot_pre3 = v2b["Pivot Status V3"].eq("突破前 >3%")
    pivot_near_fresh = v2b["Pivot Status V3"].isin(["接近Pivot 0–3%", "刚突破 0–2%"])

    st.subheader("⑤ 精确组合验证")
    st.caption(
        "上一轮显示Room的“开放”组并不强，因此本轮不再把“开放”与≥5%混合。"
        "所有组合仍只做研究，不改变V2B Core。"
    )

    variants = [
        ("V2B Benchmark", v2b),
        ("V2B + First Room ≥5%", v2b[first_ge5]),
        ("V2B + First Room ≥2%", v2b[first_ge2]),
        ("V2B + Breakout Room ≥8%", v2b[breakout_ge8]),
        ("V2B + Breakout Room ≥5%", v2b[breakout_ge5]),
        ("V2B + First≥5% + Breakout≥8%", v2b[first_ge5 & breakout_ge8]),
        ("V2B + Pivot突破前 >3%", v2b[pivot_pre3]),
        ("V2B + Pivot突破前>3% + First≥5%", v2b[pivot_pre3 & first_ge5]),
        ("V2B + Pivot突破前>3% + Breakout≥8%", v2b[pivot_pre3 & breakout_ge8]),
        ("V2B + Pivot突破前>3% + First≥5% + Breakout≥8%",
         v2b[pivot_pre3 & first_ge5 & breakout_ge8]),
        ("对照：V2B + Pivot接近/刚突破", v2b[pivot_near_fresh]),
    ]
    _render_v3_table([_v3_summary(x, lab, dates_n) for lab, x in variants])

    base_n = len(v2b)
    base_g = pd.to_numeric(v2b["5D Max Gain"], errors="coerce").dropna()
    base_5 = (base_g >= .05).mean() if len(base_g) else np.nan
    base_8 = (base_g >= .08).mean() if len(base_g) else np.nan
    base_weak = (base_g < .02).mean() if len(base_g) else np.nan

    rank_rows = []
    for lab, x in variants[1:-1]:
        g = pd.to_numeric(x["5D Max Gain"], errors="coerce").dropna()
        n = len(g)
        daily = n / max(int(dates_n), 1)
        h5 = (g >= .05).mean() if n else np.nan
        h8 = (g >= .08).mean() if n else np.nan
        weak = (g < .02).mean() if n else np.nan
        rank_rows.append({
            "组合": lab,
            "样本": n,
            "平均每天": daily,
            "保留样本%": n / base_n if base_n else np.nan,
            "Δ≥5%": h5 - base_5 if n else np.nan,
            "Δ≥8%": h8 - base_8 if n else np.nan,
            "Δ弱股<2%": weak - base_weak if n else np.nan,
            "研究判断": (
                "优先级候选"
                if n >= 60 and daily >= 1.0 and h5 >= base_5 + .04 and weak <= base_weak
                else "样本偏少"
                if n < 40
                else "观察"
            )
        })

    st.subheader("⑥ 相对V2B的净改善与样本保留")
    rdf = pd.DataFrame(rank_rows)
    st.dataframe(
        rdf.style.format({
            "平均每天":"{:.2f}", "保留样本%":"{:.1%}",
            "Δ≥5%":"{:+.1%}", "Δ≥8%":"{:+.1%}", "Δ弱股<2%":"{:+.1%}"
        }, na_rep=""),
        hide_index=True, use_container_width=True
    )

    st.info(
        "FINAL验证原则：不因为小样本命中率很高就设硬门槛。"
        "重点找≥5%/≥8%提高、弱股下降，同时仍保留足够样本和每天候选的条件。"
        "若强组合每天不足约1只，更适合做A候选优先级，而不是一票否决。"
    )


def render_historical_a_replay(bt):
    if bt is None or bt.empty:
        st.warning('历史回放没有得到有效样本。')
        return

    st.header('🎯 A6 FINAL — 历史验证')
    st.caption('验证 V2B Core 及 Pivot / Room 优先级依据；这些历史结果不改变当天正式候选资格。')
    render_a4_a5_resonance_comparison(bt)
    render_a6_v3_pivot_room_research(bt)

    d = bt.copy()
    if '5D Max Gain' in d.columns:
        d['5D Max Gain'] = pd.to_numeric(d['5D Max Gain'], errors='coerce')
    if 'Replay Date' in d.columns:
        dates_n = d['Replay Date'].nunique()
    else:
        dates_n = 0

    fix3 = d[d.get('A5决策', pd.Series(index=d.index, dtype=object)).eq('买')].copy() if 'A5决策' in d.columns else pd.DataFrame()
    if not fix3.empty:
        g = pd.to_numeric(fix3['5D Max Gain'], errors='coerce').dropna()
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric('回放交易日', int(dates_n))
        c2.metric('FIX3样本', int(len(g)))
        c3.metric('5D ≥5%', f'{(g>=.05).mean():.1%}' if len(g) else '—')
        c4.metric('5D ≥8%', f'{(g>=.08).mean():.1%}' if len(g) else '—')
        c5.metric('弱股 <2%', f'{(g<.02).mean():.1%}' if len(g) else '—')

    csv = d.to_csv(index=False).encode('utf-8-sig')
    st.download_button('💾 下载 FINAL 历史回放明细', csv,
                       file_name=f"A52R_FINAL_Replay_{dates_n}D_{datetime.now().strftime('%Y-%m-%d')}.csv",
                       mime='text/csv', use_container_width=True)

# =========================================================
# UI
# =========================================================
with st.sidebar:
    st.header("A6 FINAL")
    top_n = st.slider("次日重点候选数量", min_value=5, max_value=20, value=TOP_N_DEFAULT, step=1)
    st.markdown("**Early Engine V2 权重**")
    st.write("市场结构 25")
    st.write("趋势动量 20")
    st.write("资金积累 20")
    st.write("领导力 20")
    st.write("Catalyst 15")
    st.markdown("**Fundamental Confirmation（不计入100分）**")
    st.write("Quality / FCF / Debt / Valuation / Growth")
    st.caption("股票池：当前 S&P 500 + 原自选池；A程序是盘后选股，不是盘中买入信号。")
    st.success("A6 FINAL：V2B Core决定正式候选；Pivot/Room只做优先级排序，不做一票否决。")

st.info(
    "A6 FINAL 500池：从 GitHub Raw 读取当前 S&P 500，并保留原自选股；若读取失败会明确停止，不再偷偷退回110只。Core决定候选资格；Pivot/Room只负责排序。"
)

scan_clicked = st.button("🚀 运行 A6 FINAL 盘后扫描", type="primary", use_container_width=True)

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
            "。A6 FINAL 不会改用 Yahoo 日K混跑。"
        )

    if not available_tickers:
        st.error("Supabase 当前没有可用于 A6 FINAL 的股票日K，扫描停止。")
        st.stop()

    results = []
    for i, ticker in enumerate(available_tickers, start=1):
        status.write(f"正在分析 {ticker}（{i}/{len(available_tickers)}）")
        # Production scan intentionally does not fall back to Yahoo daily OHLCV.
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
    # A6 FINAL formal candidate pool:
    # Hard Filter pass + V2B Core BUY. Never force-fill to top_n.
    eligible = all_df[
        (all_df["Hard Filter"] == "通过")
        & (all_df["A5决策"] == "买")
    ].copy()

    quality_order = {"✅ 通过": 0, "⚠️ 观察": 1, "❌ 不适合Early": 2}
    eligible["_质量排序"] = eligible["质量检查"].map(quality_order).fillna(9)

    # Pivot/Room priority comes first; existing A quality scores break ties.
    sort_cols = [
        "_质量排序", "A6优先分", "共振数", "Early V2 Score",
        "Structure Score", "Leadership Score", "Accumulation Score"
    ]
    sort_cols = [c for c in sort_cols if c in eligible.columns]
    ascending_map = {
        "_质量排序": True, "A6优先分": False, "共振数": False,
        "Early V2 Score": False, "Structure Score": False,
        "Leadership Score": False, "Accumulation Score": False
    }
    eligible = eligible.sort_values(
        sort_cols,
        ascending=[ascending_map[c] for c in sort_cols],
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
        st.warning("当前没有符合 A6 FINAL Core 的正式候选。")
        return

    st.success(f"✅ A6 FINAL 扫描完成：{len(top_df)}只正式候选（不强制凑满）")

    display_cols = [
        # 结果放最前；最终只给“买 / 不买”
        "A5决策", "Rank", "Ticker", "Company", "Price",
        "A6优先级", "A6优先分", "A6优先原因",
        "Pivot Status V3", "First Room Status V3", "Breakout Room Status V3",
        "共振数",
        # 一个指标一个col
        "MACD共振", "KDJ共振", "RSI共振", "量价共振", "RS共振", "空间共振",
        "空间等级", "空间优先级",
        "位置判断", "A5.2R支撑区", "A5.2R压力区", "距支撑区", "上方空间",
        # 关键数值，便于复核
        "Early V2 Score", "Structure Score", "Trend & Momentum Score",
        "Accumulation Score", "Leadership Score",
        "KDJ_K", "KDJ_D", "KDJ_J", "RSI14", "MACD Phase",
        "Volume Build Ratio", "Up/Down Volume Ratio", "RS Acceleration",
        "Major Resistance Zone", "Major Support Zone", "Short-term Breakout",
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
        "上方空间": "{:+.1%}",
        "距支撑区": "{:.1%}",
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

    st.subheader("🎯 A6 FINAL — 次日正式候选")
    cn_titles = {
        "A5决策":"结果",
        "A6优先级":"优先级", "A6优先分":"优先分", "A6优先原因":"优先原因",
        "Pivot Status V3":"Pivot状态", "First Room Status V3":"First Room",
        "Breakout Room Status V3":"Breakout Room",
        "共振数":"共振数", "MACD共振":"MACD", "KDJ共振":"KDJ", "RSI共振":"RSI", "量价共振":"量价", "RS共振":"相对强度", "空间共振":"空间", "空间等级":"空间等级", "空间优先级":"空间优先级", "位置判断":"位置判断", "A5.2R支撑区":"支撑区", "A5.2R压力区":"压力区", "距支撑区":"距支撑", "上方空间":"上方空间", "KDJ_K":"K", "KDJ_D":"D", "KDJ_J":"J",
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
        "真正买点由 B/C 用1H和15min确认；买入后继续由同一个 B/C App 管理退出。"
    )

    c1, c2 = st.columns(2)
    with c1:
        csv = reorder_a_columns(top_df).rename(columns=A_SHEET_CN_MAP).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "💾 下载 A6 FINAL 候选",
            csv,
            file_name=f"A52R_FINAL_Top_{len(top_df)}_{datetime.now().strftime('%Y-%m-%d')}.csv",
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
    st.caption("点击上方按钮运行 A6 FINAL 盘后扫描。")

st.divider()
with st.expander("🧪 历史验证 / Research（平时无需打开）", expanded=False):
    st.caption(
        "这里仅用于验证 A6 FINAL，不参与每天正式盘后扫描。"
        "历史 Replay 暂使用 Yahoo 约2年日K；正式盘后扫描继续使用 Supabase 复权日线。"
    )

    replay_days = st.selectbox(
        "历史回放交易日",
        [20, 30, 60],
        index=2,
        key="a6_final_replay_days"
    )

    if st.button("运行 A6 FINAL 历史验证", use_container_width=True):
        try:
            p = st.progress(0)
            s = st.empty()
            bt = run_historical_a_replay(
                replay_days=int(replay_days),
                progress_bar=p,
                status_box=s
            )
            st.session_state["a_historical_replay"] = bt
            st.session_state["a_historical_replay_days"] = int(replay_days)
        except Exception as e:
            st.error(f"A历史回测失败：{e}")

    if "a_historical_replay" in st.session_state:
        render_historical_a_replay(st.session_state["a_historical_replay"])

    with st.expander("Forward Validation 历史库", expanded=False):
        if "a_all_history_save_msg" in st.session_state:
            st.info(st.session_state["a_all_history_save_msg"])
        st.caption("A_AllScannedHistory 用于以后做真实前瞻验证。")
        if st.button("运行 Forward Validation", use_container_width=True):
            try:
                hist = load_all_scan_history()
                if hist.empty:
                    st.warning("A_AllScannedHistory 还没有记录。")
                else:
                    st.session_state["a_strong_bt"] = evaluate_scan_history(hist)
            except Exception as e:
                st.error(f"Forward Validation失败：{e}")
        if "a_strong_bt" in st.session_state:
            render_strong_stock_backtest(st.session_state["a_strong_bt"])
