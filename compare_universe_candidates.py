#!/usr/bin/env python3
"""Compare the former index/watchlist scope with the full production universe."""
import json
from pathlib import Path
import pandas as pd
from a_daily_runner import load_production_namespace, ticker_latest_date, MAX_CANDIDATES
from a_selection_core import rank_current_a
from universe_2500 import build_universe, _build_index_seed
from load_stock_daily import get_existing_status, env

def main():
    tickers = build_universe(verbose=True)
    former = set(_build_index_seed())
    _, latest = get_existing_status(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), tickers)
    ns = load_production_namespace()
    data = ns["supabase_batch_download"](tuple(tickers))
    benchmarks = ns["get_benchmark_returns"]()
    dated = {t: ticker_latest_date(data.get(t)) for t in tickers}
    available = [d for d in dated.values() if d is not None]
    if not available:
        raise RuntimeError("No usable adjusted data")
    freshest = max(available)
    fresh = [t for t in tickers if dated[t] == freshest]
    rows = []
    for t in fresh:
        row = ns["analyze_daily_candidate"](t, data[t], benchmarks)
        if row is not None:
            row["最后数据日期"] = freshest.isoformat()
            row["范围"] = "原股票池" if t in former else "新增股票"
            rows.append(row)
    if not rows:
        raise RuntimeError("No valid analysis rows")
    all_rows = pd.DataFrame(rows)
    candidates = all_rows[all_rows["A正式候选"].astype(str).eq("是")].copy()
    old = candidates[candidates["Ticker"].isin(former)].copy()
    added = candidates[~candidates["Ticker"].isin(former)].copy()
    full = rank_current_a(candidates, MAX_CANDIDATES) if not candidates.empty else candidates
    old_ranked = rank_current_a(old, MAX_CANDIDATES) if not old.empty else old
    added_ranked = rank_current_a(added, MAX_CANDIDATES) if not added.empty else added
    out = Path("universe_comparison")
    out.mkdir(exist_ok=True)
    summary = {
        "data_date": freshest.isoformat(),
        "requested_universe": len(tickers),
        "former_scope": len([t for t in tickers if t in former]),
        "raw_history_available": len(latest),
        "raw_no_history": [t for t in tickers if t not in latest],
        "adjusted_missing": [t for t in tickers if dated[t] is None],
        "adjusted_stale": [t for t in tickers if dated[t] is not None and dated[t] < freshest],
        "fresh_tickers": len(fresh),
        "analyzed": len(all_rows),
        "former_candidate_count": len(old),
        "expanded_candidate_count": len(candidates),
        "added_candidate_count": len(added),
        "former_candidates": old_ranked.get("Ticker", pd.Series(dtype=str)).tolist(),
        "expanded_candidates": full.get("Ticker", pd.Series(dtype=str)).tolist(),
        "added_candidates": added_ranked.get("Ticker", pd.Series(dtype=str)).tolist(),
    }
    (out/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("UNIVERSE COMPARISON SUMMARY", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    for name, frame in [("former_candidates", old_ranked), ("expanded_candidates", full), ("added_candidates", added_ranked)]:
        frame.to_csv(out/(name+".csv"), index=False)
        print(name, flush=True)
        cols = [c for c in ["Rank","Ticker","Price","A核心原因","最后数据日期"] if c in frame]
        print(frame[cols].to_string(index=False) if not frame.empty else "None", flush=True)

if __name__ == "__main__":
    main()
