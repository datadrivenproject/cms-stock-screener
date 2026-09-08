import os
import sys
import math
import requests
from collections import defaultdict

BQ_URL = "https://data.businessquant.com/quotes"
TICKERS = ["AAPL", "MSFT", "NVDA"]
PERIOD = "1y"
BATCH_SIZE = 500


def fail(message):
    print(f"❌ {message}")
    sys.exit(1)


def get_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        fail(f"缺少 GitHub Secret: {name}")
    return value


def normalize_date(value):
    if not value:
        return None
    return str(value).strip()[:10]


def to_float(value):
    if value is None or value == "":
        return None
    x = float(value)
    if not math.isfinite(x):
        return None
    return x


def to_int(value):
    if value is None or value == "":
        return None
    return int(float(value))


def validate_ohlcv(row):
    required = ["open", "high", "low", "close", "volume"]
    if any(row.get(k) is None for k in required):
        return False, "OHLCV 存在空值"

    o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]

    if min(o, h, l, c) <= 0:
        return False, "价格 <= 0"
    if v < 0:
        return False, "成交量 < 0"
    if h < max(o, l, c):
        return False, "high 小于 O/L/C"
    if l > min(o, h, c):
        return False, "low 大于 O/H/C"

    return True, ""


def fetch_businessquant(api_key):
    params = {
        "ticker": ",".join(TICKERS),
        "mode": "eod",
        "period": PERIOD,
        "limit": 500,
        "page": 1,
        "api_key": api_key,
    }

    print("📥 正在从 Business Quant 下载 3 只股票的一年 EOD 数据...")
    r = requests.get(BQ_URL, params=params, timeout=90)
    print("Business Quant HTTP:", r.status_code)
    r.raise_for_status()
    result = r.json()

    if "metadata" in result and "data" in result:
        ticker = result.get("metadata", {}).get("ticker", "UNKNOWN")
        result = {ticker: result}

    return result


def clean_ticker_data(ticker, block):
    raw = block.get("data", [])
    if not raw:
        fail(f"{ticker} 没有返回 data")

    grouped = defaultdict(list)
    for item in raw:
        d = normalize_date(item.get("date"))
        if d:
            grouped[d].append(item)

    duplicate_dates = {d: rows for d, rows in grouped.items() if len(rows) > 1}
    print(f"\n{ticker}: 原始 {len(raw)} 条；唯一交易日 {len(grouped)}；重复日期 {len(duplicate_dates)}")

    cleaned = []
    conflict_count = 0

    for trade_date in sorted(grouped):
        rows = grouped[trade_date]

        normalized = []
        for item in rows:
            try:
                normalized.append({
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "open": to_float(item.get("open")),
                    "high": to_float(item.get("high")),
                    "low": to_float(item.get("low")),
                    "close": to_float(item.get("close")),
                    "volume": to_int(item.get("volume")),
                    "source": "businessquant",
                })
            except Exception as e:
                fail(f"{ticker} {trade_date} 数值转换失败: {e}")

        if len(normalized) > 1:
            signatures = {
                (x["open"], x["high"], x["low"], x["close"], x["volume"])
                for x in normalized
            }
            if len(signatures) > 1:
                conflict_count += 1
                print(f"⚠️ {ticker} {trade_date} 重复记录数值不完全一致；保留 API 返回的最后一条")

        chosen = normalized[-1]
        ok, reason = validate_ohlcv(chosen)
        if not ok:
            fail(f"{ticker} {trade_date} 数据检查失败: {reason} | {chosen}")

        cleaned.append(chosen)

    print(f"{ticker}: 清洗后 {len(cleaned)} 条；冲突重复日期 {conflict_count}")
    return cleaned


def upsert_supabase(base_url, secret_key, rows):
    endpoint = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    params = {"on_conflict": "ticker,trade_date"}
    headers = {
        "apikey": secret_key,
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    print(f"\n📤 准备写入 Supabase，共 {len(rows)} 条清洗后记录...")

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        r = requests.post(endpoint, params=params, headers=headers, json=batch, timeout=90)
        print(f"Batch {start + 1}-{start + len(batch)} HTTP:", r.status_code)
        if not r.ok:
            print("Supabase response:", r.text[:2000])
            r.raise_for_status()

    print("✅ Supabase upsert 完成")


def verify_supabase(base_url, secret_key, expected_counts):
    endpoint = f"{base_url.rstrip('/')}/rest/v1/stock_daily"
    headers = {
        "apikey": secret_key,
        "Authorization": f"Bearer {secret_key}",
        "Accept": "application/json",
    }

    print("\n🔎 回读 Supabase 验证：")

    all_ok = True
    for ticker, expected in expected_counts.items():
        params = {
            "select": "ticker,trade_date",
            "ticker": f"eq.{ticker}",
            "order": "trade_date.asc",
        }
        r = requests.get(endpoint, params=params, headers=headers, timeout=60)
        print(f"{ticker} GET HTTP:", r.status_code)
        if not r.ok:
            print(r.text[:2000])
            r.raise_for_status()

        rows = r.json()
        actual = len(rows)
        dates = [x["trade_date"] for x in rows]
        unique_dates = len(set(dates))

        print(f"{ticker}: 数据库 {actual} 条；唯一日期 {unique_dates}；本次预期至少 {expected} 条")

        if actual < expected or actual != unique_dates:
            all_ok = False

    if not all_ok:
        fail("Supabase 回读验证未通过")

    print("✅ Supabase 回读验证通过")


def main():
    print("=" * 70)
    print("CMS Data Loader V1 - Business Quant → Supabase")
    print("测试股票: AAPL, MSFT, NVDA")
    print("历史范围: 1年 EOD")
    print("=" * 70)

    bq_key = get_env("BUSINESSQUANT_API_KEY")
    supabase_url = get_env("SUPABASE_URL")
    supabase_key = get_env("SUPABASE_SERVICE_ROLE_KEY")

    if "/rest/v1" in supabase_url:
        fail("SUPABASE_URL 应为基础项目 URL，不应包含 /rest/v1/")

    result = fetch_businessquant(bq_key)

    all_rows = []
    expected_counts = {}

    for ticker in TICKERS:
        block = result.get(ticker)
        if not block:
            fail(f"Business Quant 返回结果中没有 {ticker}")

        rows = clean_ticker_data(ticker, block)
        expected_counts[ticker] = len(rows)
        all_rows.extend(rows)

    keys = [(x["ticker"], x["trade_date"]) for x in all_rows]
    if len(keys) != len(set(keys)):
        fail("清洗后仍存在 ticker + trade_date 重复")

    print(f"\n✅ 最终写入前检查通过，共 {len(all_rows)} 条唯一日K")

    upsert_supabase(supabase_url, supabase_key, all_rows)
    verify_supabase(supabase_url, supabase_key, expected_counts)

    print("\n" + "=" * 70)
    print("🎉 CMS Data Loader V1 测试成功")
    print("Business Quant → 清洗/去重 → Supabase stock_daily 已打通")
    print("=" * 70)


if __name__ == "__main__":
    main()
