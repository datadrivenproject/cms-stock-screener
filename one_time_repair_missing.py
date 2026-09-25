#!/usr/bin/env python3
"""ONE-TIME repair for tickers missing recent data. Delete after successful run."""
import time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from universe_1500 import build_universe
from load_stock_daily import (
    BQ_URL, chunks, clean, env, get_existing_status, normalize_multi_ticker_result,
    upsert, today_iso, next_calendar_day
)

def latest_one(sb_url, sb_key, ticker):
    url=f"{sb_url.rstrip('/')}/rest/v1/stock_daily"
    h={"apikey":sb_key,"Authorization":f"Bearer {sb_key}","Accept":"application/json"}
    r=requests.get(url,params={"select":"ticker,trade_date","ticker":f"eq.{ticker}",
        "order":"trade_date.desc","limit":1},headers=h,timeout=30)
    r.raise_for_status()
    x=r.json()
    return str(x[0]["trade_date"])[:10] if x else None

def fetch(api_key, tickers, start=None, end=None, history=False):
    p = {"ticker": ",".join(tickers), "mode": "daily", "limit": 500, "page": 1, "api_key": api_key}
    if history:
        end = today_iso()
        start = (datetime.strptime(end, "%Y-%m-%d").date() - timedelta(days=365)).isoformat()
    p.update({"from_date": start, "till_date": end})
    r = requests.get(BQ_URL, params=p, timeout=180)
    label = f"{start}->{end}" + (" bootstrap" if history else "")
    print(f"BQ HTTP {r.status_code}: {len(tickers)} tickers | {label}")
    r.raise_for_status()
    return normalize_multi_ticker_result(r.json(), tickers)

def main():
    bq=env("BUSINESSQUANT_API_KEY"); sb=env("SUPABASE_URL"); key=env("SUPABASE_SERVICE_ROLE_KEY")
    tickers=build_universe(verbose=True)
    _, recent=get_existing_status(sb,key,tickers)
    candidates=[t for t in tickers if t not in recent]
    if "CBOE" in tickers and "CBOE" not in candidates: candidates.append("CBOE")
    print(f"Candidates needing exact check: {len(candidates)}")
    exact={}; no_history=[]
    for i,t in enumerate(candidates,1):
        d=latest_one(sb,key,t); exact[t]=d
        if not d: no_history.append(t)
        print(f"[{i}/{len(candidates)}] {t}: {d or 'NO HISTORY'}")
    till=today_iso()
    stale=[t for t,d in exact.items() if d and d<till]
    print(f"No history: {len(no_history)} | stale: {len(stale)} | target: {till}")

    # Bootstrap only genuinely empty tickers, in small batches.
    for batch in chunks(no_history,25):
        try:
            res=fetch(bq,batch,history=True)
        except Exception as e:
            print(f"SKIP bootstrap batch (provider returned no supported history): {e}")
            print("Bootstrap tickers:", ", ".join(batch))
            continue
        rows=[]
        for t in batch: rows.extend(clean(t,res.get(t)))
        if rows: upsert(sb,key,rows)
        time.sleep(4)

    # Repair stale tickers by their exact missing window.
    groups={}
    for t in stale:
        start=next_calendar_day(exact[t]); groups.setdefault(start,[]).append(t)
    for start, names in sorted(groups.items()):
        if start>till: continue
        for batch in chunks(names,25):
            # Repair individually: one unsupported ticker must never abort the rest.
            for t in batch:
                try:
                    res=fetch(bq,[t],start,till)
                except Exception as e:
                    print(f"SKIP stale ticker {t}: {e}")
                    continue
                rows=[x for x in clean(t,res.get(t)) if x["trade_date"]>exact[t]]
                if rows: upsert(sb,key,rows)
                time.sleep(1)

    # Final exact check only for repaired candidates.
    unresolved=[]
    for t in candidates:
        d=latest_one(sb,key,t)
        if d!=till: unresolved.append((t,d))
    print(f"FINAL unresolved/not-on-target: {len(unresolved)}")
    for x in unresolved: print(" ",x)
    print("ONE-TIME REPAIR COMPLETE. This script/workflow can now be deleted.")

if __name__=="__main__": main()
