#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Send CMS production notifications to Telegram.

This module is intentionally isolated from stock-selection logic.
It only reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from environment variables
and sends text via Telegram Bot API.
"""

import os
import requests


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    # Never print the bot token. Printing only a masked chat ID is useful for
    # diagnosing GitHub Secret configuration without exposing the full value.
    masked_chat_id = ("*" * max(0, len(chat_id) - 4)) + chat_id[-4:]
    print(f"Telegram send attempt: chat_id=...{masked_chat_id[-8:]}, message_chars={len(message)}")

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Telegram network error: {exc}") from exc

    # Telegram normally returns JSON even for HTTP 4xx. Capture its description
    # before raising so Actions logs show the real cause (e.g. chat not found).
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_response": response.text[:500]}

    if not response.ok or not payload.get("ok", False):
        error_code = payload.get("error_code", response.status_code)
        description = payload.get("description", "Unknown Telegram API error")
        raise RuntimeError(
            f"Telegram send failed: HTTP {response.status_code}; "
            f"error_code={error_code}; description={description}; "
            f"chat_id_length={len(chat_id)}"
        )

    print("Telegram notification sent successfully.")
