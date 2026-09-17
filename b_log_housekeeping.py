import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib


"""Weekly housekeeping for B_Log only.

Policy:
- Keep all B_Log rows from the most recent 30 calendar days.
- Older routine monitoring rows are deleted permanently; they are NOT archived to Supabase.
- Older rows that contain an actual signal (BUY/SELL/STOP/TP1/TP2) are retained.
- A_Candidates, B_MasterList, A logic, B decision logic and market data are untouched.
"""

MARKET_TZ = ZoneInfo("America/New_York")
WORKSHEET = "B_Log"
RETENTION_DAYS = 30
SIGNAL_WORDS = ("BUY", "SELL", "STOP", "TP1", "TP2")


def _load_secrets():
    with open(".streamlit/secrets.toml", "rb") as f:
        return tomllib.load(f)


def _worksheet():
    secrets = _load_secrets()
    svc = secrets.get("gcp_service_account")
    tracker = secrets.get("tracker", {})
    sheet_name = tracker.get("sheet_name") if isinstance(tracker, dict) else None
    if not isinstance(svc, dict) or not sheet_name:
        raise RuntimeError("Missing [gcp_service_account] or [tracker].sheet_name")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(dict(svc), scopes=scopes)
    return gspread.authorize(creds).open(str(sheet_name)).worksheet(WORKSHEET)


def _parse_date(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _has_signal(row, headers):
    preferred = ["盘中决策", "最后决策", "状态", "Decision"]
    fields = [row[headers.index(c)] for c in preferred if c in headers and headers.index(c) < len(row)]
    if not fields:
        fields = row
    text = " ".join(str(x).upper() for x in fields)
    return any(word in text for word in SIGNAL_WORDS)


def _ranges_descending(row_numbers):
    if not row_numbers:
        return []
    nums = sorted(set(row_numbers))
    ranges = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append((start, prev))
            start = prev = n
    ranges.append((start, prev))
    return list(reversed(ranges))


def main():
    ws = _worksheet()
    values = ws.get_all_values()
    if len(values) <= 1:
        print("B_Log empty; nothing to clean.")
        return

    headers = values[0]
    date_col = next((c for c in ("检查日期", "扫描日期", "日期") if c in headers), None)
    if date_col is None:
        raise RuntimeError("B_Log missing 检查日期/扫描日期/日期; cleanup aborted safely")
    date_idx = headers.index(date_col)

    cutoff = datetime.now(MARKET_TZ).date() - timedelta(days=RETENTION_DAYS)
    delete_rows = []
    kept_old_signals = 0
    unparsed = 0

    for sheet_row, row in enumerate(values[1:], start=2):
        d = _parse_date(row[date_idx] if date_idx < len(row) else "")
        if d is None:
            unparsed += 1
            continue
        if d < cutoff:
            if _has_signal(row, headers):
                kept_old_signals += 1
            else:
                delete_rows.append(sheet_row)

    for start, end in _ranges_descending(delete_rows):
        ws.delete_rows(start, end)

    print(f"B_Log retention: {RETENTION_DAYS} days")
    print(f"Cutoff date: {cutoff.isoformat()}")
    print(f"Deleted old routine rows: {len(delete_rows)}")
    print(f"Kept old signal rows: {kept_old_signals}")
    print(f"Rows with unparsed dates kept safely: {unparsed}")
    print("No Supabase archive created.")
    print("A_Candidates and B_MasterList untouched.")


if __name__ == "__main__":
    main()
