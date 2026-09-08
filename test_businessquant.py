import os
import sys
import requests
from datetime import datetime


API_URL = "https://data.businessquant.com/quotes"
TICKERS = ["AAPL", "MSFT", "NVDA"]


def main():
    api_key = os.getenv("BUSINESSQUANT_API_KEY")

    if not api_key:
        print("❌ BUSINESSQUANT_API_KEY 没有找到")
        sys.exit(1)

    print("=" * 60)
    print("CMS Data Engine V1 - Business Quant Test")
    print("测试股票:", ", ".join(TICKERS))
    print("模式: EOD")
    print("历史范围: 1年")
    print("=" * 60)

    params = {
        "ticker": ",".join(TICKERS),
        "mode": "eod",
        "period": "1y",
        "limit": 500,
        "page": 1,
        "api_key": api_key,
    }

    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=60
        )

        print("HTTP Status:", response.status_code)

        response.raise_for_status()

        result = response.json()

    except Exception as e:
        print("❌ API 请求失败:")
        print(str(e))
        sys.exit(1)

    # Business Quant:
    # 单 ticker -> {"metadata": ..., "data": [...]}
    # 多 ticker -> {"AAPL": {...}, "MSFT": {...}}
    if "metadata" in result and "data" in result:
        ticker = result.get("metadata", {}).get("ticker", "UNKNOWN")
        result = {ticker: result}

    success_count = 0

    for ticker in TICKERS:

        print()
        print("=" * 60)
        print(f"检查 {ticker}")
        print("=" * 60)

        block = result.get(ticker)

        if not block:
            print(f"❌ 没有取得 {ticker} 数据")
            continue

        metadata = block.get("metadata", {})
        data = block.get("data", [])

        print("公司:", metadata.get("companyname"))
        print("记录数:", len(data))
        print("From:", metadata.get("from_date"))
        print("To:", metadata.get("till_date"))

        pagination = metadata.get("pagination", {})

        print(
            "Pagination:",
            f"page={pagination.get('current_page')}",
            f"total_records={pagination.get('total_records')}",
            f"total_pages={pagination.get('total_pages')}",
        )

        if not data:
            print("❌ data 是空的")
            continue

        required_fields = {
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        missing_rows = []
        dates = []

        for i, row in enumerate(data):
            missing = required_fields - set(row.keys())

            if missing:
                missing_rows.append((i, missing))

            if row.get("date"):
                dates.append(row["date"])

        if missing_rows:
            print("❌ 有记录缺少 OHLCV 字段:")
            print(missing_rows[:5])
            continue

        duplicate_dates = len(dates) - len(set(dates))

        print("OHLCV字段: ✅")
        print("重复日期数量:", duplicate_dates)

        # 日期排序，仅用于检查
        sorted_data = sorted(
            data,
            key=lambda x: x.get("date", "")
        )

        first = sorted_data[0]
        latest = sorted_data[-1]

        print()
        print("最早一条:")
        print(first)

        print()
        print("最新一条:")
        print(latest)

        print()
        print("最近3个交易日:")

        for row in sorted_data[-3:]:
            print(
                row["date"],
                "O:", row["open"],
                "H:", row["high"],
                "L:", row["low"],
                "C:", row["close"],
                "V:", row["volume"],
            )

        # 正常1年大约250个交易日
        if 200 <= len(data) <= 270:
            print("一年数据量: ✅ 正常")
        else:
            print(
                f"⚠️ 一年记录数为 {len(data)}，需要进一步检查"
            )

        if duplicate_dates == 0:
            print("日期唯一性: ✅")
        else:
            print("⚠️ 存在重复交易日期，需要在进入 Supabase 前处理")

        success_count += 1

    print()
    print("=" * 60)

    if success_count == len(TICKERS):
        print("✅ Business Quant API 基础测试完成")
        print("下一步：连接 Supabase stock_daily")
    else:
        print(
            f"⚠️ 成功 {success_count}/{len(TICKERS)} 个 ticker"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
