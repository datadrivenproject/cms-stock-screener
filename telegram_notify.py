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

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")
