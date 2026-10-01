#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Send the latest AI Final_Review to Telegram once per Toronto trading date.
Notification-only: does not modify A/Q/M selection logic.
"""

import json
import os
import tomllib
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram_notify import send_telegram

OUTPUT_TAB = "Final_Review"
MARKER_HEADER = "AI_Telegram_Sent_Date"
TOP_N = 5


def main():
    raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    book_name = os.getenv("TRACKER_SHEET_NAME", "").strip()
    if not raw or not book_name:
        raise RuntimeError("Missing Google Sheet secrets")

    try:
        service_account = json.loads(raw)
    except Exception:
        parsed = tomllib.loads(raw)
        service_account = parsed.get("gcp_service_account", parsed)
    if not isinstance(service_account, dict) or "client_email" not in service_account:
        raise RuntimeError("Invalid Google service-account secret format")

    creds = Credentials.from_service_account_info(
        service_account,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    book = gspread.authorize(creds).open(book_name)
    ws = book.worksheet(OUTPUT_TAB)
    rows = ws.get_all_records()
    if not rows:
        print("Final_Review is empty; nothing to send.")
        return

    today = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d")
    latest_date = str(rows[0].get("记录日期", "")).strip()
    if latest_date != today:
        print(f"Final_Review is not ready for today: latest={latest_date}, today={today}")
        return

    # N1/N2 are outside the A:M review output. review.py clears the sheet before
    # each fresh review, so a new review automatically resets this marker.
    if ws.acell("N1").value == MARKER_HEADER and ws.acell("N2").value == today:
        print(f"AI Telegram already sent for {today}; skip duplicate.")
        return

    def score(row):
        try:
            return int(float(row.get("AI信心分", 0) or 0))
        except Exception:
            return 0

    rows = sorted(rows, key=lambda r: int(float(r.get("最终排名", 9999) or 9999)))
    top = rows[:TOP_N]

    lines = [f"🤖 AI Final Review — {today}", f"今日候选：{len(rows)}只", ""]
    for i, r in enumerate(top, 1):
        ticker = str(r.get("股票", "")).strip()
        decision = str(r.get("最终结论", "观望")).strip()
        s = score(r)
        icon = "🟢" if decision == "买入" else ("🔴" if decision == "不买" else "🟡")
        lines.append(f"#{i} {ticker} | {icon}{decision} | AI {s}")

    buys = [str(r.get("股票", "")).strip() for r in rows if str(r.get("最终结论", "")).strip() == "买入"]
    lines += ["", "重点：" + ("、".join(buys[:5]) if buys else "今日无AI买入")]

    send_telegram("\n".join(lines))
    ws.update("N1:N2", [[MARKER_HEADER], [today]])
    print(f"AI Final Review Telegram sent for {today}.")


if __name__ == "__main__":
    main()
