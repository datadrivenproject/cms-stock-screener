#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS A5.2R FINAL — HEADLESS DAILY RUNNER v1.0

IMPORTANT:
- This file does NOT duplicate A5.2R strategy logic.
- It loads the production functions/constants directly from the current repo's app.py.
- Therefore Streamlit A and scheduled A use ONE strategy source of truth.
- It automatically writes:
    A_Candidates
    A_AllScannedHistory

Required GitHub Secrets:
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- GCP_SERVICE_ACCOUNT_JSON
  Accepts either full JSON or the existing Streamlit [gcp_service_account] TOML block.
- TRACKER_SHEET_NAME
"""

import ast
import json
import os
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pandas_market_calendars as mcal


APP_FILE = Path(__file__).with_name("app.py")
TOP_N = 10


def env(name):
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing GitHub Secret: {name}")
    return v


def parse_google_service_account(raw):
    try:
        info = json.loads(raw)
        if isinstance(info, dict) and "client_email" in info and "private_key" in info:
            return info
    except Exception:
        pass

    try:
        parsed = tomllib.loads(raw)
        info = parsed.get("gcp_service_account", parsed)
        if isinstance(info, dict) and "client_email" in info and "private_key" in info:
            return info
    except Exception as e:
        raise RuntimeError(
            "GCP_SERVICE_ACCOUNT_JSON must contain either full Google service-account JSON "
            "or the Streamlit [gcp_service_account] TOML block."
        ) from e

    raise RuntimeError("Could not parse Google service-account secret.")


class _NoCache:
    def __call__(self, func=None, **kwargs):
        if func is not None and callable(func):
            return func
        def deco(f):
            return f
        return deco


class _HeadlessStreamlit:
    """
    Minimal compatibility layer used only while loading production definitions
    from app.py. No Streamlit UI executes.
    """
    def __init__(self, secrets):
        self.secrets = secrets
        self.cache_data = _NoCache()

    def stop(self):
        raise RuntimeError("Production A requested st.stop() in headless mode.")


def load_production_namespace():
    if not APP_FILE.exists():
        raise RuntimeError(f"Production A file not found: {APP_FILE}")

    source = APP_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(APP_FILE))

    # Load imports/constants/functions only from the production portion before UI.
    # We intentionally exclude Streamlit page rendering and all button code.
    selected = []
    for node in tree.body:
        lineno = getattr(node, "lineno", 0)

        if lineno >= 3232:
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            selected.append(node)
            continue

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            # Constants are safe; skip assignments that directly reference st.
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "st" not in names:
                selected.append(node)
            continue

        if isinstance(node, ast.Import):
            # app.py's "import streamlit as st" is replaced by our headless shim.
            kept = [a for a in node.names if a.name != "streamlit"]
            if kept:
                selected.append(ast.Import(names=kept))
            continue

        if isinstance(node, ast.ImportFrom):
            selected.append(node)
            continue

        if isinstance(node, ast.Try):
            # Keeps the app.py gspread/google-auth optional-import block.
            selected.append(node)
            continue

        # One non-UI expression before line 3232 updates the Chinese column map.
        if isinstance(node, ast.Expr) and lineno == 1826:
            selected.append(node)

    mod = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(mod)

    service_account = parse_google_service_account(env("GCP_SERVICE_ACCOUNT_JSON"))
    fake_secrets = {
        "SUPABASE_URL": env("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": env("SUPABASE_SERVICE_ROLE_KEY"),
        "gcp_service_account": service_account,
        "tracker": {"sheet_name": env("TRACKER_SHEET_NAME")},
    }

    ns = {
        "__name__": "cms_a_production_core",
        "__file__": str(APP_FILE),
        "st": _HeadlessStreamlit(fake_secrets),
    }

    exec(compile(mod, str(APP_FILE), "exec"), ns, ns)

    required = [
        "get_universe",
        "supabase_batch_download",
        "get_benchmark_returns",
        "analyze_daily_candidate",
        "save_daily_candidates",
        "save_all_scanned_history",
        "BENCHMARK_TICKERS",
    ]
    missing = [name for name in required if name not in ns]
    if missing:
        raise RuntimeError(
            "Current app.py structure changed and headless runner could not find: "
            + ", ".join(missing)
        )

    return ns


def _latest_completed_nyse_session(now=None):
    """
    Return the latest NYSE session that should already have a completed daily bar.

    - On a NYSE trading day after 16:15 ET, today is expected.
    - Before 16:15 ET, use the prior NYSE session.
    - On weekends / holidays, use the prior NYSE session.
    """
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    now = now or datetime.now(ny)

    cal = mcal.get_calendar("NYSE")
    start = (pd.Timestamp(now.date()) - pd.Timedelta(days=14)).date()
    end = pd.Timestamp(now.date()).date()
    sched = cal.schedule(start_date=start, end_date=end)

    sessions = [pd.Timestamp(x).date() for x in sched.index]
    if not sessions:
        raise RuntimeError("Could not resolve recent NYSE sessions.")

    today = now.date()
    if today in sessions and now.time() >= time(16, 15):
        return today

    prior = [d for d in sessions if d < today]
    if not prior:
        raise RuntimeError("Could not resolve prior NYSE session.")
    return prior[-1]


def _nyse_session_lag(latest_data_date, expected_session):
    """
    Count completed NYSE sessions AFTER latest_data_date through expected_session.
    0 = current, 1 = one session stale, 2 = two sessions stale, etc.
    """
    if latest_data_date is None:
        return 999

    latest_data_date = pd.Timestamp(latest_data_date).date()
    expected_session = pd.Timestamp(expected_session).date()

    if latest_data_date >= expected_session:
        return 0

    cal = mcal.get_calendar("NYSE")
    sched = cal.schedule(
        start_date=latest_data_date,
        end_date=expected_session
    )
    sessions = [pd.Timestamp(x).date() for x in sched.index]
    return sum(1 for d in sessions if latest_data_date < d <= expected_session)


def validate_daily_freshness(data, benchmarks, tolerance_sessions=1):
    """
    Safety gate before A writes anything.

    Rules:
    - Uses actual NYSE sessions, not plain weekdays.
    - Every stock and benchmark must be no more than `tolerance_sessions`
      completed NYSE sessions behind.
    - If stale beyond tolerance, A stops BEFORE A_Candidates /
      A_AllScannedHistory are written.
    """
    expected = _latest_completed_nyse_session()

    latest_by_symbol = {}

    for ticker, df in data.items():
        if df is None or df.empty:
            continue
        latest_by_symbol[str(ticker).upper()] = pd.Timestamp(df.index.max()).date()

    # benchmark frames are already summarized to returns, so reload their latest
    # dates from the same production Supabase source for the freshness check.
    bench_frames = ns_for_freshness["supabase_batch_download"](
        tuple(ns_for_freshness["BENCHMARK_TICKERS"])
    )
    for ticker, df in bench_frames.items():
        if df is None or df.empty:
            continue
        latest_by_symbol[str(ticker).upper()] = pd.Timestamp(df.index.max()).date()

    required = set(ns_for_freshness["get_universe"]()) | set(ns_for_freshness["BENCHMARK_TICKERS"])
    missing = sorted(t for t in required if t not in latest_by_symbol)
    if missing:
        raise RuntimeError(
            "Freshness check failed: missing latest adjusted daily data for: "
            + ", ".join(missing)
        )

    stale = []
    one_session_stale = []
    current = []

    for ticker in sorted(required):
        d = latest_by_symbol[ticker]
        lag = _nyse_session_lag(d, expected)
        if lag > tolerance_sessions:
            stale.append((ticker, d, lag))
        elif lag == 1:
            one_session_stale.append((ticker, d))
        else:
            current.append((ticker, d))

    print("\n🛡 DAILY DATA FRESHNESS CHECK", flush=True)
    print(f"Expected latest completed NYSE session: {expected}", flush=True)
    print(f"Current symbols: {len(current)}", flush=True)
    print(f"1-session stale but allowed: {len(one_session_stale)}", flush=True)
    print(f"Too stale (> {tolerance_sessions} session): {len(stale)}", flush=True)

    if one_session_stale:
        sample = ", ".join(f"{t}:{d}" for t, d in one_session_stale[:12])
        print(f"Allowed stale sample: {sample}", flush=True)

    if stale:
        details = ", ".join(f"{t}:{d}({lag} sessions)" for t, d, lag in stale[:30])
        raise RuntimeError(
            "A scan blocked by stale Supabase adjusted daily data. "
            f"Expected session={expected}; stale symbols: {details}"
        )

    print("✅ Freshness gate passed. A scan may continue.", flush=True)



def main():
    print("=" * 90, flush=True)
    print("CMS A5.2R FINAL — HEADLESS DAILY RUNNER", flush=True)
    print("Strategy source: current production app.py (single source of truth)", flush=True)
    print("=" * 90, flush=True)

    ns = load_production_namespace()

    tickers = ns["get_universe"]()
    print(f"Universe: {len(tickers)} stocks", flush=True)

    print("\n📥 Reading adjusted daily OHLCV from Supabase...", flush=True)
    data = ns["supabase_batch_download"](tuple(tickers))
    benchmarks = ns["get_benchmark_returns"]()

    # Expose the already-loaded production namespace only to the freshness helper.
    # No strategy logic is duplicated here.
    global ns_for_freshness
    ns_for_freshness = ns

    # Safety gate: stop before any Google Sheet write if adjusted daily data
    # is more than 1 completed NYSE session stale.
    validate_daily_freshness(data, benchmarks, tolerance_sessions=1)

    missing_bench = [t for t in ns["BENCHMARK_TICKERS"] if t not in benchmarks]
    if missing_bench:
        raise RuntimeError(
            "Missing adjusted benchmark data: " + ", ".join(missing_bench)
        )

    missing_daily = [
        t for t in tickers
        if t not in data or data[t] is None or data[t].empty
    ]
    if missing_daily:
        raise RuntimeError(
            "Missing adjusted stock data; scan blocked to avoid mixed price basis: "
            + ", ".join(missing_daily)
        )

    results = []
    for i, ticker in enumerate(tickers, 1):
        row = ns["analyze_daily_candidate"](ticker, data[ticker], benchmarks)
        if row is not None:
            results.append(row)
        print(f"[{i:03d}/{len(tickers)}] {ticker}", flush=True)

    if not results:
        raise RuntimeError("A scan produced no valid results.")

    all_df = pd.DataFrame(results)

    eligible = all_df[all_df["Hard Filter"] == "通过"].copy()
    quality_order = {"✅ 通过": 0, "⚠️ 观察": 1, "❌ 不适合Early": 2}
    eligible["_质量排序"] = eligible["质量检查"].map(quality_order).fillna(9)
    eligible = eligible.sort_values(
        [
            "_质量排序",
            "Early V2 Score",
            "Structure Score",
            "Leadership Score",
            "Accumulation Score",
        ],
        ascending=[True, False, False, False, False],
    ).drop(columns=["_质量排序"]).reset_index(drop=True)

    eligible["Rank"] = eligible.index + 1
    top_df = eligible.head(TOP_N).copy()

    print("\n💾 Saving A_AllScannedHistory...", flush=True)
    n_all, u_all = ns["save_all_scanned_history"](all_df)
    print(f"   added={n_all}, updated={u_all}", flush=True)

    print("\n💾 Saving A_Candidates...", flush=True)
    n, u = ns["save_daily_candidates"](top_df)
    print(f"   added={n}, updated={u}", flush=True)

    buys = top_df[top_df["A5决策"].astype(str).str.strip().eq("买")].copy()

    print("\n" + "=" * 90, flush=True)
    print("A DAILY SUMMARY", flush=True)
    print(f"Analyzed: {len(all_df)}", flush=True)
    print(f"Hard-filter eligible: {len(eligible)}", flush=True)
    print(f"Top candidates saved: {len(top_df)}", flush=True)
    print(f"Formal A5.2R BUY: {len(buys)}", flush=True)

    if not buys.empty:
        show = [
            c for c in
            ["Rank","Ticker","Company","A5决策","共振数","空间等级","上方空间"]
            if c in buys.columns
        ]
        print(buys[show].to_string(index=False), flush=True)
    else:
        print("No formal BUY today.", flush=True)

    print("\n✅ A5.2R scheduled scan completed and A_Candidates updated.", flush=True)


if __name__ == "__main__":
    main()
