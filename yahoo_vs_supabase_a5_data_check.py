import os
import sys
import requests
import pandas as pd
import numpy as np
import yfinance as yf

TICKERS = ["AAPL", "NVDA", "TSLA", "PLUG", "TEM"]
LOOKBACK = "1y"


def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def env(name):
    value = os.getenv(name, "").strip()
    if not value:
        fail(f"缺少 GitHub Secret: {name}")
    return value


def rsi(series, period=14):
    s = pd.to_numeric(series, errors="coerce")
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out


def macd_hist(series):
    s = pd.to_numeric(series, errors="coerce")
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def fetch_supabase(ticker, base_url, api_key):
    url = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    params = {
        "select": "trade_date,open,high,low,close,volume",
        "ticker": f"eq.{ticker}",
        "order": "trade_date.asc",
    }
    r = requests.get(url, headers=headers, params=params, timeout=60)
    print(f"Supabase {ticker} HTTP:", r.status_code)
    if not r.ok:
        print(r.text[:1000])
        r.raise_for_status()

    data = r.json()
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()

    rename = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df = df.rename(columns=rename)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df[["Open", "High", "Low", "Close", "Volume"]]


def fetch_yahoo(ticker):
    df = yf.download(
        ticker,
        period=LOOKBACK,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].copy()


def pct_diff(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    denom = b.replace(0, np.nan).abs()
    return (a - b).abs() / denom


def compare_one(ticker, sb, yh):
    common = sb.index.intersection(yh.index)
    if len(common) < 100:
        return None, None

    s = sb.loc[common].copy()
    y = yh.loc[common].copy()

    close_diff = pct_diff(s["Close"], y["Close"])
    open_diff = pct_diff(s["Open"], y["Open"])
    high_diff = pct_diff(s["High"], y["High"])
    low_diff = pct_diff(s["Low"], y["Low"])

    s_ma20 = s["Close"].rolling(20).mean()
    y_ma20 = y["Close"].rolling(20).mean()

    s_rsi = rsi(s["Close"])
    y_rsi = rsi(y["Close"])

    _, _, s_hist = macd_hist(s["Close"])
    _, _, y_hist = macd_hist(y["Close"])

    latest = common.max()

    # Price ratio can reveal whether one source is consistently adjusted.
    ratio = (s["Close"] / y["Close"]).replace([np.inf, -np.inf], np.nan).dropna()
    ratio_std = float(ratio.std()) if len(ratio) else np.nan
    ratio_min = float(ratio.min()) if len(ratio) else np.nan
    ratio_max = float(ratio.max()) if len(ratio) else np.nan

    summary = {
        "Ticker": ticker,
        "共同交易日": int(len(common)),
        "Close平均差异%": float(close_diff.mean() * 100),
        "Close最大差异%": float(close_diff.max() * 100),
        "OHLC最大差异%": float(pd.concat([open_diff, high_diff, low_diff, close_diff], axis=1).max().max() * 100),
        "最新YahooClose": float(y.loc[latest, "Close"]),
        "最新SupabaseClose": float(s.loc[latest, "Close"]),
        "最新Close差异%": float(close_diff.loc[latest] * 100),
        "最新MA20差异%": float(abs(s_ma20.loc[latest] - y_ma20.loc[latest]) / abs(y_ma20.loc[latest]) * 100)
            if pd.notna(s_ma20.loc[latest]) and pd.notna(y_ma20.loc[latest]) and y_ma20.loc[latest] != 0 else np.nan,
        "最新RSI差异": float(abs(s_rsi.loc[latest] - y_rsi.loc[latest]))
            if pd.notna(s_rsi.loc[latest]) and pd.notna(y_rsi.loc[latest]) else np.nan,
        "最新MACD柱差异": float(abs(s_hist.loc[latest] - y_hist.loc[latest]))
            if pd.notna(s_hist.loc[latest]) and pd.notna(y_hist.loc[latest]) else np.nan,
        "价格比率Std": ratio_std,
        "价格比率Min": ratio_min,
        "价格比率Max": ratio_max,
    }

    detail = pd.DataFrame({
        "Date": common,
        "Yahoo_Close": y["Close"].values,
        "Supabase_Close": s["Close"].values,
        "Close_Diff_Pct": (close_diff.values * 100),
        "Yahoo_MA20": y_ma20.values,
        "Supabase_MA20": s_ma20.values,
        "Yahoo_RSI": y_rsi.values,
        "Supabase_RSI": s_rsi.values,
        "Yahoo_MACD_Hist": y_hist.values,
        "Supabase_MACD_Hist": s_hist.values,
    })

    return summary, detail


def classify(row):
    if row is None:
        return "无数据"
    maxd = row["Close最大差异%"]
    latestd = row["最新Close差异%"]
    ratio_std = row["价格比率Std"]

    if maxd < 0.15 and latestd < 0.15:
        return "✅ 基本一致"
    if ratio_std < 0.005 and maxd >= 0.15:
        return "⚠️ 疑似稳定复权比例差"
    return "⚠️ 历史序列存在结构性差异"


def main():
    sb_url = env("SUPABASE_URL")
    sb_key = env("SUPABASE_SERVICE_ROLE_KEY")

    print("=" * 76)
    print("CMS A5 Data Check — Yahoo auto_adjust=True vs Supabase/Business Quant")
    print("股票:", ", ".join(TICKERS))
    print("=" * 76)

    summaries = []
    details = []

    for t in TICKERS:
        print(f"\n🔎 检查 {t}")
        sb = fetch_supabase(t, sb_url, sb_key)
        yh = fetch_yahoo(t)

        print(f"  Supabase bars: {len(sb)} | Yahoo bars: {len(yh)}")

        if sb.empty or yh.empty:
            print("  ❌ 数据不足")
            continue

        summary, detail = compare_one(t, sb, yh)
        if summary is None:
            print("  ❌ 共同交易日不足")
            continue

        summary["判断"] = classify(summary)
        summaries.append(summary)

        detail.insert(0, "Ticker", t)
        details.append(detail)

        print(
            f"  共同日={summary['共同交易日']} | "
            f"Close平均差异={summary['Close平均差异%']:.4f}% | "
            f"最大差异={summary['Close最大差异%']:.4f}% | "
            f"最新差异={summary['最新Close差异%']:.4f}% | "
            f"{summary['判断']}"
        )

    if not summaries:
        fail("没有得到可比较结果")

    out = pd.DataFrame(summaries)

    print("\n" + "=" * 76)
    print("汇总")
    print("=" * 76)
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(out.to_string(index=False))

    out.to_csv("yahoo_vs_supabase_summary.csv", index=False, encoding="utf-8-sig")

    if details:
        pd.concat(details, ignore_index=True).to_csv(
            "yahoo_vs_supabase_detail.csv",
            index=False,
            encoding="utf-8-sig",
        )

    print("\n✅ 已生成:")
    print("  yahoo_vs_supabase_summary.csv")
    print("  yahoo_vs_supabase_detail.csv")
    print("\n判读原则:")
    print("  - 若 Close 差异接近 0：Business Quant 与 Yahoo auto_adjust 基本同口径")
    print("  - 若历史差异明显但最新 Close 接近：通常是历史复权口径不同")
    print("  - 若连最新 Close 都明显不同：需检查数据日期/交易日/数据质量")


if __name__ == "__main__":
    main()
