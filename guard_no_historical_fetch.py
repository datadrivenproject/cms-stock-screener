#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS PRODUCTION SAFETY GUARD

Hard rule for DAILY production:
- Historical BusinessQuant pulls are forbidden.
- Daily updater may use BusinessQuant ONLY with from_date + till_date.
- The adjuster must NEVER call BusinessQuant.

This script is intentionally run BEFORE any market-data step in GitHub Actions.
If a future edit accidentally re-introduces period=1y/history loading into the
production path, the workflow stops before consuming BusinessQuant quota.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent

DAILY_UPDATER = ROOT / "load_stock_daily_529.py"
ADJUSTER = ROOT / "adjust_stock_daily_529.py"
WORKFLOW = ROOT / ".github" / "workflows" / "a_daily_pipeline.yml"


def fail(messages):
    print("\n❌ CMS DATA SAFETY GUARD FAILED")
    for msg in messages:
        print(" -", msg)
    print("\nDaily production is blocked BEFORE any BusinessQuant request.")
    sys.exit(1)


def read(path):
    if not path.exists():
        fail([f"Required production file missing: {path.relative_to(ROOT)}"])
    return path.read_text(encoding="utf-8")


def main():
    errors = []
    daily = read(DAILY_UPDATER)
    adjust = read(ADJUSTER)
    workflow = read(WORKFLOW)

    # ---------------------------------------------------------
    # 1) Daily updater: ONLY date-window incremental BQ requests
    # ---------------------------------------------------------
    # Remove comments/docstrings approximately by checking active-code patterns.
    forbidden_daily_patterns = [
        (r"['\"]period['\"]\s*:\s*['\"]1y['\"]", "daily updater contains period=1y"),
        (r"period\s*=\s*['\"]1y['\"]", "daily updater contains period=1y"),
        (r"PERIOD\s*=\s*['\"]1y['\"]", "daily updater defines 1-year history period"),
    ]
    for pattern, label in forbidden_daily_patterns:
        if re.search(pattern, daily, flags=re.I):
            errors.append(label)

    if '"from_date"' not in daily or '"till_date"' not in daily:
        errors.append("daily updater must use from_date + till_date incremental window")

    if "REQUEST_BATCH = 100" not in daily:
        errors.append("daily updater expected BusinessQuant request batch size 100")

    # ---------------------------------------------------------
    # 2) Adjuster: ZERO BusinessQuant access allowed
    # ---------------------------------------------------------
    forbidden_adjust_tokens = [
        "data.businessquant.com",
        "BUSINESSQUANT_API_KEY",
        "BQ_URL",
        "period=1y",
        '"period":',
        "'period':",
    ]
    for token in forbidden_adjust_tokens:
        if token.lower() in adjust.lower():
            errors.append(f"adjuster is Supabase-only; forbidden token found: {token}")

    # ---------------------------------------------------------
    # 3) Workflow itself must run this guard before updater
    # ---------------------------------------------------------
    guard_pos = workflow.find("guard_no_historical_fetch.py")
    updater_pos = workflow.find("load_stock_daily_529.py")
    if guard_pos < 0:
        errors.append("workflow does not run guard_no_historical_fetch.py")
    elif updater_pos >= 0 and guard_pos > updater_pos:
        errors.append("safety guard must run before load_stock_daily_529.py")

    if errors:
        fail(errors)

    print("✅ CMS DATA SAFETY GUARD PASSED")
    print("   Daily BQ mode: TRUE incremental only (from_date -> till_date)")
    print("   Daily BQ batch target: 100 tickers/request")
    print("   Adjuster: Supabase-only; BusinessQuant access forbidden")
    print("   Historical/1y production fetch: BLOCKED")


if __name__ == "__main__":
    main()
