#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""CMS A — KD-CORE HEADLESS DAILY RUNNER.

Production rules:
- app.py remains the source of truth for A正式候选 and indicator calculations.
- Small isolated missing adjusted-data gaps are skipped rather than killing A.
- FRESHNESS GATE: only tickers whose latest adjusted date equals the freshest
  date available in the current universe may participate in today's A scan.
- 资金积累分 is display/secondary information only; it is NOT an eligibility filter.
- This file does NOT change app.py.
"""

import ast
import json
import os
import tomllib
from pathlib import Path

import pandas as pd
from telegram_notify import send_telegram
from a_selection_core import rank_current_a

APP_FILE = Path(__file__).with_name("app.py")
MAX_CANDIDATES = 20
# A few symbols can be unavailable or unsupported by the data source.
# Do not block the whole production scan; skip them and keep the freshness gate.
MAX_MISSING_TICKERS = None


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
    raise RuntimeError("GCP_SERVICE_ACCOUNT_JSON must be full service-account JSON or a Streamlit [gcp_service_account] TOML block.")


class _NoCache:
    def __call__(self, func=None, **kwargs):
        if func is not None and callable(func):
            return func
        def deco(f): return f
        return deco


class _HeadlessStreamlit:
    def __init__(self, secrets):
        self.secrets = secrets
        self.cache_data = _NoCache()
        self.session_state = {}
    def stop(self):
        raise RuntimeError("app.py requested st.stop() while running headless A")


def load_production_namespace():
    source = APP_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(APP_FILE))
    selected = []
    for node in tree.body:
        lineno = getattr(node, "lineno", 0)
        if lineno >= 3232: continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            selected.append(node); continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "st" not in names: selected.append(node)
            continue
        if isinstance(node, ast.Import):
            kept = [a for a in node.names if a.name != "streamlit"]
            if kept: selected.append(ast.Import(names=kept))
            continue
        if isinstance(node, ast.ImportFrom):
            # Imports from app.py are resolved normally; the locked A rule now
            # lives in a_selection_core.py instead of being duplicated inline.
            selected.append(node); continue
        if isinstance(node, ast.Try): selected.append(node); continue
        if isinstance(node, ast.Expr) and lineno == 1826: selected.append(node)

    service_account = parse_google_service_account(env("GCP_SERVICE_ACCOUNT_JSON"))
    fake_secrets = {
        "SUPABASE_URL": env("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": env("SUPABASE_SERVICE_ROLE_KEY"),
        "gcp_service_account": service_account,
        "tracker": {"sheet_name": env("TRACKER_SHEET_NAME")},
    }
    ns = {"__name__": "cms_a_production_core", "__file__": str(APP_FILE), "st": _HeadlessStreamlit(fake_secrets)}
    mod = ast.Module(body=selected, type_ignores=[]); ast.fix_missing_locations(mod)
    exec(compile(mod, str(APP_FILE), "exec"), ns, ns)
    required = ["get_universe", "supabase_batch_download", "get_benchmark_returns", "analyze_daily_candidate", "save_daily_candidates"]
    missing = [name for name in required if name not in ns]
    if missing: raise RuntimeError("Could not load from app.py: " + ", ".join(missing))
    return ns


def ticker_latest_date(df):
    if df is None or df.empty: return None
    try: return pd.Timestamp(df.index.max()).date()
    except Exception: return None


def build_telegram_summary(formal, freshest_date, universe_count, stale_count):
    lines = [
        f"CMS A Daily — {freshest_date.isoformat()}",
        f"Universe: {universe_count} | Stale excluded: {stale_count}",
        f"KD-Core candidates: {len(formal)}",
    ]
    if formal.empty:
        lines.append("No formal candidate today.")
        return "\n".join(lines)
    lines.append("")
    for i, (_, row) in enumerate(formal.head(10).iterrows(), 1):
        ticker = str(row.get("Ticker", "?"))
        price = row.get("Price", "")
        grade = str(row.get("A候选等级", ""))
        accum = row.get("资金积累总分", "")
        atr = row.get("ATR%", "")
        drawdown = row.get("APEX近期回撤%", "")
        stop_confirm = str(row.get("APEX止跌确认", ""))
        vol_confirm = str(row.get("APEX放量转强", ""))
        vol_ratio = row.get("APEX量比20", "")
        ret5 = row.get("5D Return", "")
        k = row.get("KDJ_K", "")
        d = row.get("KDJ_D", "")

        parts = [f"{i}. {ticker}"]
        if str(price) not in ("", "nan"): parts.append(f"Price {float(price):.2f}")
        if grade and grade != "nan": parts.append(grade)
        lines.append(" | ".join(parts))

        core = []
        if str(ret5) not in ("", "nan"): core.append(f"5D {float(ret5):+.1%}")
        if str(atr) not in ("", "nan"): core.append(f"ATR {float(atr):.1%}")
        if str(k) not in ("", "nan") and str(d) not in ("", "nan"):
            core.append(f"KD {float(k):.1f}/{float(d):.1f}")
        if str(accum) not in ("", "nan"): core.append(f"积累 {accum}")
        if core: lines.append("   A核心: " + " | ".join(core))

        apex = []
        if str(drawdown) not in ("", "nan"): apex.append(f"20D回撤 {float(drawdown):.1%}")
        if stop_confirm: apex.append(f"止跌{'✓' if stop_confirm == '是' else '✗'}")
        if vol_confirm: apex.append(f"放量转强{'✓' if vol_confirm == '是' else '✗'}")
        if str(vol_ratio) not in ("", "nan"): apex.append(f"量比 {float(vol_ratio):.2f}x")
        if apex: lines.append("   APEX: " + " | ".join(apex))
    if len(formal) > 10: lines.append(f"... plus {len(formal)-10} more")
    return "\n".join(lines)


def main():
    print("=" * 88, flush=True)
    print("CMS A — KD-CORE HEADLESS DAILY RUNNER", flush=True)
    print("Selection source of truth: app.py A正式候选 (no extra accumulation cutoff)", flush=True)
    print("Freshness gate: ON — stale tickers cannot participate in today's A scan.", flush=True)
    print("=" * 88, flush=True)

    ns = load_production_namespace(); tickers = ns["get_universe"]()
    print(f"Universe: {len(tickers)} stocks", flush=True)
    data = ns["supabase_batch_download"](tuple(tickers)); benchmarks = ns["get_benchmark_returns"]()
    missing = [t for t in tickers if t not in data or data[t] is None or data[t].empty]
    if missing and len(missing) > MAX_MISSING_TICKERS:
        raise RuntimeError(f"A scan blocked: adjusted Supabase data missing for {len(missing)} tickers: " + ", ".join(missing[:40]))
    if missing: print(f"⚠️ Missing adjusted data skipped ({len(missing)}): " + ", ".join(missing), flush=True)
    dated = {t: ticker_latest_date(data.get(t)) for t in tickers if t not in missing}; dated = {t:d for t,d in dated.items() if d is not None}
    if not dated: raise RuntimeError("A scan blocked: no usable dated adjusted Supabase data")
    freshest_date = max(dated.values()); fresh_tickers = [t for t in tickers if dated.get(t) == freshest_date]
    stale_tickers = [t for t in tickers if t in dated and dated[t] < freshest_date]
    print(f"Freshest adjusted date: {freshest_date.isoformat()}", flush=True)
    print(f"Fresh tickers: {len(fresh_tickers)}", flush=True); print(f"Stale tickers excluded today: {len(stale_tickers)}", flush=True)
    if not fresh_tickers: raise RuntimeError("A scan blocked: no ticker passed freshness gate")
    rows=[]
    for i,ticker in enumerate(fresh_tickers,1):
        row=ns["analyze_daily_candidate"](ticker,data[ticker],benchmarks)
        if row is not None: row["最后数据日期"]=freshest_date.isoformat(); rows.append(row)
        print(f"[{i:03d}/{len(fresh_tickers)}] {ticker}",flush=True)
    if not rows: raise RuntimeError("A scan produced no valid rows")
    all_df=pd.DataFrame(rows); formal=all_df[all_df.get("A正式候选","否").astype(str).eq("是")].copy()
    if not formal.empty:
        # Exact existing production ordering, now centralized with the locked A rule.
        formal=rank_current_a(formal, MAX_CANDIDATES)
    result=ns["save_daily_candidates"](formal)
    print("\n"+"="*88,flush=True); print("KD-CORE DAILY SUMMARY",flush=True)
    print(f"Requested universe: {len(tickers)}",flush=True); print(f"Freshest date: {freshest_date.isoformat()}",flush=True)
    print(f"Missing adjusted: {len(missing)}",flush=True); print(f"Stale excluded: {len(stale_tickers)}",flush=True)
    print(f"Fresh universe analyzed: {len(all_df)}",flush=True); print(f"app.py formal KD candidates: {len(formal)}",flush=True)
    print("Extra accumulation eligibility filter: OFF",flush=True); print(f"Sheet result: {result}",flush=True)
    if not formal.empty:
        cols=[c for c in ["Rank","Ticker","Price","A候选等级","A核心原因","5D Return","ATR%","KDJ_K","KDJ_D","资金积累总分","资金积累解释","恐慌释放分","最后数据日期"] if c in formal.columns]
        print(formal[cols].to_string(index=False),flush=True)
    else: print("No app.py formal KD-Core candidate today.",flush=True)

    message = build_telegram_summary(formal, freshest_date, len(tickers), len(stale_tickers))
    send_telegram(message)
    print("✅ Telegram daily summary sent.", flush=True)
    print("✅ KD-Core scheduled scan completed with freshness gate.",flush=True)


if __name__=="__main__": main()
