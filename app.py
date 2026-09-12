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
st.set_page_config(page_title="CMS KD 20/80 — Core", page_icon="📈", layout="wide")

st.title("📈 CMS KD 20/80 — 低位金叉 / 高位死叉")
st.caption(
    "盘后正式候选：强势资格 + Startup Transition V3（至少2个新鲜触发 + 启动分≥5 + 位置确认）。"
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
    # Positive RSI resonance requires RSI to be non-declining on the current bar.
    rsi_ok = bool((50 <= rsi <= 72) and (rsi >= rsi_prev))

    # ---------- CMS 新核心：KD 20/80 ----------
    # 只用 K、D 的交叉和位置做交易触发，不再让 MACD / RSI / 量价 / RS 决定买卖。
    # 买：K 今日上穿 D，且交叉发生在低位区（当前或前一交易日 K/D 至少一个 <= 20）。
    # 卖：K 今日下穿 D，且交叉发生在高位区（当前或前一交易日 K/D 至少一个 >= 80）。
    kd_diff = k - d
    kd_cross_up_today = bool((kd_diff.iloc[-1] > 0) and (kd_diff.iloc[-2] <= 0))
    kd_cross_down_today = bool((kd_diff.iloc[-1] < 0) and (kd_diff.iloc[-2] >= 0))

    kd_low_20 = bool(min(k0, d0, k1, d1) <= 20)
    kd_high_80 = bool(max(k0, d0, k1, d1) >= 80)

    kd_buy = bool(kd_cross_up_today and kd_low_20)
    kd_sell = bool(kd_cross_down_today and kd_high_80)
    kd_action = "买" if kd_buy else ("卖" if kd_sell else "观察")

    # 仅用于排序/展示：越接近低位20的金叉优先，不参与是否触发。
    kd_buy_zone = min(k0, d0) if kd_buy else np.nan
    kd_sell_zone = max(k0, d0) if kd_sell else np.nan

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




def _independent_signals(x, cooldown_sessions=5, all_dates=None):
    """Keep the first signal per ticker within each non-overlapping forward window."""
    if x is None or x.empty:
        return x.copy() if isinstance(x, pd.DataFrame) else pd.DataFrame()
    out = x.copy()
    source_dates = all_dates if all_dates is not None else out['Replay Date']
    dates = sorted(pd.Series(source_dates).dropna().astype(str).unique())
    date_order = {d: i for i, d in enumerate(dates)}
    out['_date_order_ab'] = out['Replay Date'].astype(str).map(date_order)
    out = out.sort_values(['Ticker', '_date_order_ab'])
    keep = []
    last_kept = {}
    for idx, r in out.iterrows():
        ticker = str(r['Ticker'])
        pos = int(r['_date_order_ab'])
        if ticker not in last_kept or pos - last_kept[ticker] >= int(cooldown_sessions):
            keep.append(idx)
            last_kept[ticker] = pos
    return out.loc[keep].drop(columns=['_date_order_ab'], errors='ignore')


def render_kd_strategy_validation(bt):
    """Validate the new KD 20/80 core without comparing it with retired strategies."""
    if bt is None or bt.empty:
        st.warning('历史回放没有得到有效样本。')
        return

    d = bt.copy()
    req = [
        'Replay Date','Ticker','Price','Dollar Volume',
        'KD低位金叉20','KD高位死叉80','KDJ_K','KDJ_D','KDJ_J',
        '1D Max Gain','3D Max Gain','5D Max Gain','5D Close Return','5D Max Drawdown'
    ]
    missing = [c for c in req if c not in d.columns]
    if missing:
        st.warning('KD 20/80 回测字段不完整，请重新运行历史验证。缺少：' + '、'.join(missing))
        return

    for c in ['Price','Dollar Volume','KDJ_K','KDJ_D','KDJ_J','1D Max Gain','3D Max Gain','5D Max Gain','5D Close Return','5D Max Drawdown']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['Replay Date','Ticker','Price'])
    if d.empty:
        return

    # 仅保留最基础的可交易性条件；不再用旧 MA/MACD/RSI/共振硬门槛。
    pool = d[(d['Price'] >= 5) & (d['Dollar Volume'] >= 20_000_000)].copy()
    buys = pool[pool['KD低位金叉20'].eq('是')].copy()
    buys = _independent_signals(buys, 5, pool['Replay Date'])

    g1 = pd.to_numeric(buys['1D Max Gain'], errors='coerce').dropna()
    g3 = pd.to_numeric(buys['3D Max Gain'], errors='coerce').dropna()
    g5 = pd.to_numeric(buys['5D Max Gain'], errors='coerce').dropna()
    c5 = pd.to_numeric(buys['5D Close Return'], errors='coerce').dropna()
    dd = pd.to_numeric(buys['5D Max Drawdown'], errors='coerce').dropna()
    dates_n = max(pool['Replay Date'].nunique(), 1)

    st.header('🎯 KD 20/80 历史验证')
    st.caption('正式核心：低位20金叉买入；高位80死叉卖出。历史区只验证这一套新核心。')

    c1,c2,c3,c4,c5m,c6 = st.columns(6)
    c1.metric('独立买入信号', int(len(buys)))
    c2.metric('平均每天', f'{len(buys)/dates_n:.2f}')
    c3.metric('1D ≥3%', f'{(g1>=.03).mean():.1%}' if len(g1) else '—')
    c4.metric('3D ≥3%', f'{(g3>=.03).mean():.1%}' if len(g3) else '—')
    c5m.metric('5D ≥5%', f'{(g5>=.05).mean():.1%}' if len(g5) else '—')
    c6.metric('5D ≥8%', f'{(g5>=.08).mean():.1%}' if len(g5) else '—')

    s1,s2,s3,s4 = st.columns(4)
    s1.metric('平均5D最大涨幅', f'{g5.mean():+.2%}' if len(g5) else '—')
    s2.metric('中位数5D最大涨幅', f'{g5.median():+.2%}' if len(g5) else '—')
    s3.metric('平均5D收盘收益', f'{c5.mean():+.2%}' if len(c5) else '—')
    s4.metric('平均5D最大回撤', f'{dd.mean():+.2%}' if len(dd) else '—')

    # 在回放日期内配对：低位金叉买入 -> 之后首个高位死叉卖出。
    trades = []
    z = pool.sort_values(['Ticker','Replay Date']).copy()
    z['Replay Date'] = pd.to_datetime(z['Replay Date'])
    for ticker, g in z.groupby('Ticker'):
        g = g.sort_values('Replay Date').reset_index(drop=True)
        in_pos = False
        entry_date = entry_px = None
        entry_i = None
        for i, r in g.iterrows():
            if (not in_pos) and r['KD低位金叉20'] == '是':
                in_pos = True
                entry_date = r['Replay Date']
                entry_px = float(r['Price'])
                entry_i = i
            elif in_pos and r['KD高位死叉80'] == '是':
                exit_px = float(r['Price'])
                ret = exit_px / entry_px - 1 if entry_px and entry_px > 0 else np.nan
                trades.append({
                    '股票代码': ticker, '买入日期': entry_date, '买入价': entry_px,
                    '卖出日期': r['Replay Date'], '卖出价': exit_px,
                    '持有交易日': int(i-entry_i), '收益率': ret
                })
                in_pos = False
                entry_date = entry_px = entry_i = None

    tdf = pd.DataFrame(trades)
    if not tdf.empty:
        rr = pd.to_numeric(tdf['收益率'], errors='coerce').dropna()
        st.subheader('🔁 20买 → 80卖 完整闭环（仅统计回放窗口内已完成交易）')
        q1,q2,q3,q4 = st.columns(4)
        q1.metric('完成交易', len(rr))
        q2.metric('胜率', f'{(rr>0).mean():.1%}' if len(rr) else '—')
        q3.metric('平均每笔收益', f'{rr.mean():+.2%}' if len(rr) else '—')
        q4.metric('中位数收益', f'{rr.median():+.2%}' if len(rr) else '—')
        with st.expander('查看已完成交易明细', expanded=False):
            st.dataframe(tdf.style.format({'买入价':'{:.2f}','卖出价':'{:.2f}','收益率':'{:+.2%}'}, na_rep='—'), hide_index=True, use_container_width=True)
    else:
        st.info('当前回放窗口内没有形成完整的“20低位金叉买入 → 80高位死叉卖出”闭环；可把回放天数加长后继续验证。')

    detail_cols = ['Replay Date','Ticker','KDJ_K','KDJ_D','KDJ_J','1D Max Gain','3D Max Gain','5D Max Gain','5D Close Return','5D Max Drawdown']
    detail = buys[[c for c in detail_cols if c in buys.columns]].sort_values('Replay Date', ascending=False)
    with st.expander('查看 KD 低位金叉买入明细', expanded=False):
        st.dataframe(detail.style.format({
            'KDJ_K':'{:.1f}','KDJ_D':'{:.1f}','KDJ_J':'{:.1f}',
            '1D Max Gain':'{:+.2%}','3D Max Gain':'{:+.2%}','5D Max Gain':'{:+.2%}',
            '5D Close Return':'{:+.2%}','5D Max Drawdown':'{:+.2%}'
        }, na_rep='—'), hide_index=True, use_container_width=True)


def render_historical_a_replay(bt):
    if bt is None or bt.empty:
        st.warning('历史回放没有得到有效样本。')
        return
    render_kd_strategy_validation(bt)
    dates_n = bt['Replay Date'].nunique() if 'Replay Date' in bt.columns else 0
    csv = bt.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        '💾 下载 KD 20/80 历史回放明细', csv,
        file_name=f"KD_20_80_Replay_{dates_n}D_{datetime.now().strftime('%Y-%m-%d')}.csv",
        mime='text/csv', use_container_width=True
    )

# =========================================================
# UI
# =========================================================
with st.sidebar:
    st.header("CMS KD 20/80")
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
    st.success("正式核心已切换：KD低位20金叉买入，高位80死叉卖出。")

st.info(
    "股票池继续使用当前 S&P 500 + 原自选股；交易触发只看 KD 20/80，旧 MACD/RSI/共振不再决定候选资格。"
)

scan_clicked = st.button("🚀 运行 KD 20/80 盘后扫描", type="primary", use_container_width=True)

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
            "。KD 20/80 正式扫描不会改用 Yahoo 日K混跑。"
        )

    if not available_tickers:
        st.error("Supabase 当前没有可用于 KD 20/80 的股票日K，扫描停止。")
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
    # CMS KD 20/80 正式候选：只让 KD 低位金叉决定是否入选。
    # 保留最基础的可交易性要求（价格和成交额），不再用旧 MACD/RSI/共振/Startup 门槛。
    eligible = all_df[
        (pd.to_numeric(all_df["Price"], errors="coerce") >= 5)
        & (pd.to_numeric(all_df["Dollar Volume"], errors="coerce") >= 20_000_000)
        & (all_df["KD低位金叉20"] == "是")
    ].copy()

    eligible["_KD排序"] = pd.to_numeric(eligible.get("KD买入区值"), errors="coerce")
    eligible["_成交额排序"] = pd.to_numeric(eligible.get("Dollar Volume"), errors="coerce")
    eligible = eligible.sort_values(
        ["_KD排序", "_成交额排序"],
        ascending=[True, False],
    ).drop(columns=["_KD排序", "_成交额排序"], errors="ignore").reset_index(drop=True)

    eligible["Rank"] = eligible.index + 1
    # KD 信号有几只就显示几只，不强制凑数，也不因 top_n 截断。
    top_df = eligible.copy()

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
        st.warning("今天没有出现 KD 低位20金叉买入信号。")
        # 即使没有买入，也显示全市场出现的高位80死叉，便于已有持仓检查卖点。
        if all_df is not None and not all_df.empty and 'KD高位死叉80' in all_df.columns:
            sells = all_df[all_df['KD高位死叉80'].eq('是')].copy()
            if not sells.empty:
                st.subheader('🔴 KD 高位80死叉 — 卖出检查')
                cols = [c for c in ['Ticker','Company','Price','KDJ_K','KDJ_D','KDJ_J','KD交易动作'] if c in sells.columns]
                show = sells[cols].rename(columns={'Ticker':'股票代码','Company':'公司','Price':'当前价格','KDJ_K':'K','KDJ_D':'D','KDJ_J':'J','KD交易动作':'动作'})
                st.dataframe(show.style.format({'当前价格':'{:.2f}','K':'{:.1f}','D':'{:.1f}','J':'{:.1f}'}, na_rep=''), hide_index=True, use_container_width=True)
        return

    st.success(f"✅ KD 20/80 扫描完成：{len(top_df)}只低位金叉买入候选")
    st.caption('核心规则：K 上穿 D 且交叉位于20低位区 → 买；K 下穿 D 且交叉位于80高位区 → 卖。MACD、RSI和旧共振不再决定买卖。')

    display_cols = [c for c in [
        'Rank','Ticker','Company','Price','KD交易动作',
        'KDJ_K','KDJ_D','KDJ_J','KD低位20','KD当日金叉','KD买入区值',
        'Dollar Volume','ATR14','5D Return','20D Return'
    ] if c in top_df.columns]
    rename = {
        'Rank':'排名','Ticker':'股票代码','Company':'公司','Price':'当前价格','KD交易动作':'动作',
        'KDJ_K':'K','KDJ_D':'D','KDJ_J':'J','KD低位20':'低位≤20','KD当日金叉':'今日金叉',
        'KD买入区值':'交叉区值','Dollar Volume':'成交额','ATR14':'ATR14','5D Return':'5日涨跌幅','20D Return':'20日涨跌幅'
    }
    show = top_df[display_cols].rename(columns=rename)
    st.subheader('🟢 KD 低位20金叉 — 买入候选')
    st.dataframe(show.style.format({
        '当前价格':'{:.2f}','K':'{:.1f}','D':'{:.1f}','J':'{:.1f}','交叉区值':'{:.1f}',
        '成交额':'{:,.0f}','ATR14':'{:.2f}','5日涨跌幅':'{:+.1%}','20日涨跌幅':'{:+.1%}'
    }, na_rep=''), hide_index=True, use_container_width=True)

    if all_df is not None and not all_df.empty and 'KD高位死叉80' in all_df.columns:
        sells = all_df[all_df['KD高位死叉80'].eq('是')].copy()
        if not sells.empty:
            st.subheader('🔴 KD 高位80死叉 — 卖出检查')
            cols = [c for c in ['Ticker','Company','Price','KDJ_K','KDJ_D','KDJ_J','KD卖出区值','KD交易动作'] if c in sells.columns]
            sh = sells[cols].rename(columns={'Ticker':'股票代码','Company':'公司','Price':'当前价格','KDJ_K':'K','KDJ_D':'D','KDJ_J':'J','KD卖出区值':'交叉区值','KD交易动作':'动作'})
            st.dataframe(sh.style.format({'当前价格':'{:.2f}','K':'{:.1f}','D':'{:.1f}','J':'{:.1f}','交叉区值':'{:.1f}'}, na_rep=''), hide_index=True, use_container_width=True)



if "v43a_top_df" in st.session_state and "v43a_all_df" in st.session_state:
    render_results(st.session_state["v43a_top_df"], st.session_state["v43a_all_df"])
else:
    st.caption("点击上方按钮运行 KD 20/80 盘后扫描。")

st.divider()
with st.expander("🧪 历史验证 / Research（平时无需打开）", expanded=False):
    st.caption(
        "这里仅用于验证 KD 20/80 核心，不参与每天正式盘后扫描。"
        "历史 Replay 暂使用 Yahoo 约2年日K；正式盘后扫描继续使用 Supabase 复权日线。"
    )

    replay_days = st.selectbox(
        "历史回放交易日",
        [20, 30, 60],
        index=2,
        key="a6_final_replay_days"
    )

    if st.button("运行历史验证：KD 20买 / 80卖", use_container_width=True):
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
