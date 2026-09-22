#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""CMS production safety guard.

DAILY production rules:
- BusinessQuant history requests are forbidden.
- The daily updater must use from_date + till_date only.
- REQUEST_BATCH must remain 100 unless deliberately reviewed.
- The adjusted-OHLC step must not contain executable BusinessQuant access.

Important: this guard inspects the Python AST, so comments/docstrings that mention
old history logic do NOT create false alarms.
"""

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DAILY_UPDATER = ROOT / "load_stock_daily_529.py"
ADJUSTER = ROOT / "adjust_stock_daily.py"
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


def parse(path):
    text = read(path)
    try:
        return text, ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        fail([f"Python syntax error in {path.name}: {exc}"])


def assigned_constant(tree, name):
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, ast.Constant):
                        values.append(node.value.value)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name:
                if isinstance(node.value, ast.Constant):
                    values.append(node.value.value)
    return values


def dict_literal_pairs(tree):
    """Yield executable literal dict key/value pairs from Python code."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                v = value.value if isinstance(value, ast.Constant) else None
                yield key.value, v


def executable_strings_and_names(tree):
    """Collect executable identifiers/string constants, excluding docstrings."""
    names = set()
    strings = []

    docstring_nodes = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_nodes.add(first.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node not in docstring_nodes:
                strings.append(node.value)
    return names, strings


def main():
    errors = []

    daily_text, daily_tree = parse(DAILY_UPDATER)
    adjust_text, adjust_tree = parse(ADJUSTER)
    workflow = read(WORKFLOW)

    # ---------------------------------------------------------
    # 1) Daily updater: executable code must be true-incremental
    # ---------------------------------------------------------
    for value in assigned_constant(daily_tree, "PERIOD"):
        if str(value).strip().lower() in {"1y", "1yr", "1year", "1 year"}:
            errors.append("daily updater defines executable 1-year history PERIOD")

    pairs = list(dict_literal_pairs(daily_tree))
    for key, value in pairs:
        if key.lower() == "period" and str(value).strip().lower() in {
            "1y", "1yr", "1year", "1 year"
        }:
            errors.append("daily updater contains executable period=1y request")

    dict_keys = {str(k) for k, _ in pairs}
    if "from_date" not in dict_keys or "till_date" not in dict_keys:
        errors.append("daily updater must use executable from_date + till_date request fields")

    batch_values = assigned_constant(daily_tree, "REQUEST_BATCH")
    if 100 not in batch_values:
        errors.append("daily updater expected REQUEST_BATCH = 100")

    # ---------------------------------------------------------
    # 2) Adjuster: executable code must have ZERO BQ access
    # ---------------------------------------------------------
    adjust_names, adjust_strings = executable_strings_and_names(adjust_tree)
    forbidden_names = {"BQ_URL", "BUSINESSQUANT_API_KEY"}
    found_names = sorted(forbidden_names & adjust_names)
    for name in found_names:
        errors.append(f"adjuster is Supabase-only; forbidden executable name: {name}")

    for text in adjust_strings:
        low = text.lower()
        if "data.businessquant.com" in low:
            errors.append("adjuster is Supabase-only; executable BusinessQuant URL found")
        if "period=1y" in low:
            errors.append("adjuster is Supabase-only; executable period=1y found")

    # ---------------------------------------------------------
    # 3) Guard itself must execute before daily updater
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
    print("   Adjuster: Supabase-only; executable BusinessQuant access forbidden")
    print("   Historical/1y production fetch: BLOCKED")


if __name__ == "__main__":
    main()
