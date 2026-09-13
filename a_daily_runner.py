#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMS A — KD-CORE HEADLESS DAILY RUNNER

Purpose
-------
Run the SAME stock-analysis functions already defined in app.py, but without
rendering Streamlit UI.  The scheduled A job therefore uses app.py as the
single source of truth for the KD signal and supporting fields.

Current production selection used by this runner:
  1) app.py must mark A正式候选 == 是
     (currently strict KD20 low-zone golden cross + prior 5D decline >=3%
      + ATR% >=4%; app.py also labels the >=5% decline tier as stronger)
  2) explainable accumulation confirmation >= ACCUMULATION_MIN_SCORE
  3) candidates are ranked by A优先级 first, then accumulation score,
     then panic-release score.  Old Early V2 / Structure / Leadership /
     Catalyst scores do NOT decide eligibility or ranking here.

This file does NOT change app.py.
"""

import ast
import json
import os
import tomllib
from pathlib import Path

import pandas as pd


APP_FILE = Path(__file__).with_name("app.py")
ACCUMULATION_MIN_SCORE = 8   # 8/20 = minimum confirmation; easy to tune later
MAX_CANDIDATES = 20          # not a quota; fewer are kept when fewer qualify


def env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Secret: {name}")
    return value


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
    except Exception:
        pass

    raise RuntimeError(
        "GCP_SERVICE_ACCOUNT_JSON must be full service-account JSON or a "
        "Streamlit [gcp_service_account] TOML block."
    )


class _NoCache:
    def __call__(self, func=None, **kwargs):
        if func is not None and callable(func):
            return func
        def deco(f):
            return f
        return deco


class _HeadlessStreamlit:
    def __init__(self, secrets):
        self.secrets = secrets
        self.cache_data = _NoCache()
        self.session_state = {}

    def stop(self):
        raise RuntimeError("app.py requested st.stop() while running headless A")


def load_production_namespace():
    """Load imports/constants/functions from app.py, but never render its UI."""
    source = APP_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(APP_FILE))

    selected = []
    for node in tree.body:
        lineno = getattr(node, "lineno", 0)

        # Current app.py UI begins after the production function section.
        # Keep the same safety boundary used by the previous runner.
        if lineno >= 3232:
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            selected.append(node)
            continue

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "st" not in names:
                selected.append(node)
            continue

        if isinstance(node, ast.Import):
            kept = [a for a in node.names if a.name != "streamlit"]
            if kept:
                selected.append(ast.Import(names=kept))
            continue

        if isinstance(node, ast.ImportFrom):
            selected.append(node)
            continue

        if isinstance(node, ast.Try):
            selected.append(node)
            continue

        # app.py has a map update expression in the production section.
        if isinstance(node, ast.Expr) and lineno == 1826:
            selected.append(node)

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

    mod = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(APP_FILE), "exec"), ns, ns)

    required = [
        "get_universe",
        "supabase_batch_download",
        "get_benchmark_returns",
        "analyze_daily_candidate",
        "save_daily_candidates",
    ]
    missing = [name for name in required if name not in ns]
    if missing:
        raise RuntimeError("Could not load from app.py: " + ", ".join(missing))

    return ns


def latest_data_date(data):
    dates = []
    for df in data.values():
        if df is not None and not df.empty:
            dates.append(pd.Timestamp(df.index.max()).date())
    return max(dates).isoformat() if dates else "未知"


def main():
    print("=" * 88, flush=True)
    print("CMS A — KD-CORE HEADLESS DAILY RUNNER", flush=True)
    print(f"Accumulation confirmation: >= {ACCUMULATION_MIN_SCORE}/20", flush=True)
    print("Old Early V2 / Structure / Leadership / Catalyst are NOT eligibility gates.", flush=True)
    print("=" * 88, flush=True)

    ns = load_production_namespace()
    tickers = ns["get_universe"]()
    print(f"Universe: {len(tickers)} stocks", flush=True)

    data = ns["supabase_batch_download"](tuple(tickers))
    benchmarks = ns["get_benchmark_returns"]()

    missing = [t for t in tickers if t not in data or data[t] is None or data[t].empty]
    if missing:
        raise RuntimeError(
            "A scan blocked: adjusted Supabase data missing for " + ", ".join(missing[:40])
        )

    scan_date = latest_data_date(data)
    print(f"Latest adjusted data date: {scan_date}", flush=True)

    rows = []
    for i, ticker in enumerate(tickers, 1):
        row = ns["analyze_daily_candidate"](ticker, data[ticker], benchmarks)
        if row is not None:
            row["最后数据日期"] = scan_date
            rows.append(row)
        print(f"[{i:03d}/{len(tickers)}] {ticker}", flush=True)

    if not rows:
        raise RuntimeError("A scan produced no valid rows")

    all_df = pd.DataFrame(rows)

    # Formal KD-Core trigger comes directly from current app.py.
    formal = all_df[all_df.get("A正式候选", "否").astype(str).eq("是")].copy()

    # Accumulation is the final confirmation layer requested for KD-Core.
    accum = pd.to_numeric(formal.get("资金积累总分"), errors="coerce").fillna(0)
    formal = formal[accum >= ACCUMULATION_MIN_SCORE].copy()

    if not formal.empty:
        formal["_a_priority"] = pd.to_numeric(formal.get("A优先级"), errors="coerce").fillna(9)
        formal["_accum"] = pd.to_numeric(formal.get("资金积累总分"), errors="coerce").fillna(0)
        formal["_panic"] = pd.to_numeric(formal.get("恐慌释放分"), errors="coerce").fillna(0)
        formal = formal.sort_values(
            ["_a_priority", "_accum", "_panic"],
            ascending=[True, False, False],
        ).drop(columns=["_a_priority", "_accum", "_panic"])
        formal = formal.head(MAX_CANDIDATES).reset_index(drop=True)
        formal["Rank"] = formal.index + 1

    # Important: save_daily_candidates does NOT clear the previous sheet when
    # there are zero candidates.  That protects B from an accidental empty scan.
    result = ns["save_daily_candidates"](formal)

    print("\n" + "=" * 88, flush=True)
    print("KD-CORE DAILY SUMMARY", flush=True)
    print(f"Analyzed: {len(all_df)}", flush=True)
    print(f"app.py formal KD candidates: {(all_df.get('A正式候选', '否').astype(str) == '是').sum()}", flush=True)
    print(f"After accumulation >= {ACCUMULATION_MIN_SCORE}: {len(formal)}", flush=True)
    print(f"Sheet result: {result}", flush=True)

    if not formal.empty:
        cols = [
            c for c in [
                "Rank", "Ticker", "Price", "A候选等级", "A核心原因",
                "5D Return", "ATR%", "KDJ_K", "KDJ_D",
                "资金积累总分", "资金积累解释", "恐慌释放分"
            ] if c in formal.columns
        ]
        print(formal[cols].to_string(index=False), flush=True)
    else:
        print("No KD-Core candidate passed accumulation confirmation today.", flush=True)

    print("✅ KD-Core scheduled scan completed.", flush=True)


if __name__ == "__main__":
    main()
