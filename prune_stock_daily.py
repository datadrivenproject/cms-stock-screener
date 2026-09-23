"""Keep only the most recent 365 calendar days of US stock_daily bars."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TABLE = "stock_daily"
RETENTION_DAYS = 365
WINDOW_DAYS = 7


def headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"}


def range_to_delete(oldest: date, today: date):
    cutoff = today - timedelta(days=RETENTION_DAYS)
    cursor = oldest
    while cursor < cutoff:
        stop = min(cursor + timedelta(days=WINDOW_DAYS), cutoff)
        yield cursor, stop
        cursor = stop


def read_boundary(session, endpoint: str, key: str, order: str) -> date | None:
    response = session.get(endpoint, headers=headers(key), params={
        "select": "trade_date", "order": f"trade_date.{order}", "limit": "1",
    }, timeout=30)
    response.raise_for_status()
    rows = response.json()
    return date.fromisoformat(rows[0]["trade_date"][:10]) if rows else None


def prune(session, base_url: str, key: str, today: date) -> int:
    if not base_url.startswith("https://") or "/rest/v1" in base_url:
        raise ValueError("SUPABASE_URL 必须是 HTTPS 项目基础 URL")
    if not key:
        raise ValueError("缺少 SUPABASE_SERVICE_ROLE_KEY")
    endpoint = f"{base_url.rstrip('/')}/rest/v1/{TABLE}"
    oldest = read_boundary(session, endpoint, key, "asc")
    if oldest is None:
        print("stock_daily 为空；无需清理")
        return 0
    latest = read_boundary(session, endpoint, key, "desc")
    if latest is None or latest < today - timedelta(days=7):
        raise RuntimeError("行情最新日期已超过七天未更新；暂停清理，先检查数据下载")
    windows = 0
    cutoff = today - timedelta(days=RETENTION_DAYS)
    for start, stop in range_to_delete(oldest, today):
        response = session.delete(endpoint, headers=headers(key), params={
            "trade_date": f"gte.{start.isoformat()}",
            "and": f"(trade_date.lt.{stop.isoformat()})",
        }, timeout=120)
        response.raise_for_status()
        windows += 1
    if windows:
        remaining_oldest = read_boundary(session, endpoint, key, "asc")
        if remaining_oldest is not None and remaining_oldest < cutoff:
            raise RuntimeError(f"清理后仍有超期日线：最早日期 {remaining_oldest}")
    print(f"美股日线清理完成：保留 {cutoff.isoformat()} 起的数据；已处理 {windows} 个日期窗口")
    return windows


def main() -> None:
    import requests

    today = datetime.now(ZoneInfo("America/New_York")).date()
    prune(requests, os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], today)


if __name__ == "__main__":
    main()
