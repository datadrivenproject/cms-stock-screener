#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, math, requests
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

STOCKS_110 = [
"AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","ORCL","IBM","DELL","HPE","SMCI",
"CRM","ADBE","NOW","PLTR","PATH","CRWD","PANW","FTNT","DDOG","NET","SNOW","MDB","ZS","OKTA","TEAM",
"QCOM","MU","INTC","ARM","MRVL","AMAT","LRCX","KLAC","ON","MCHP",
"JPM","BAC","WFC","GS","MS","V","MA","AXP","PYPL","COIN","HOOD","SOFI","XYZ","NU","IBKR",
"LLY","UNH","ABBV","MRK","AMGN","JNJ","PFE","GILD","ISRG","TMO","TEM","VEEV","REGN","VRTX","DXCM",
"XOM","CVX","COP","CAT","GE","BA","RTX","LMT","ETN","VRT","PLUG","FCX","SLB","FSLR","CEG",
"WMT","COST","HD","DIS","UBER","ABNB","DASH","BKNG","SHOP","MELI","RBLX","SPOT","ROKU","DUOL","RDDT",
"CRCL","APP","RKLB","ASTS","IONQ","RGTI","SOUN","HIMS","CAVA","CVNA"
]
BENCHMARKS_12 = ["SPY","XLK","XLV","XLF","XLY","XLP","XLI","XLE","XLB","XLU","XLRE","XLC"]
TICKERS = STOCKS_110 + BENCHMARKS_12

BQ_CORP_URL = "https://data.businessquant.com/corporate_actions"
DB_PAGE_SIZE = 1000
DB_WRITE_BATCH = 500
NY = ZoneInfo("America/New_York")

def fail(msg):
    print(f"❌ {msg}", flush=True); sys.exit(1)

def env(name):
    v=os.getenv(name,"").strip()
    if not v: fail(f"Missing GitHub Secret: {name}")
    return v

def fnum(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def headers(key):
    return {"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"}

def fetch_raw(sb_url,sb_key,ticker):
    url=f"{sb_url.rstrip('/')}/rest/v1/stock_daily"
    out=[]; offset=0
    while True:
        p={"select":"ticker,trade_date,open,high,low,close,volume",
           "ticker":f"eq.{ticker}","order":"trade_date.asc","limit":DB_PAGE_SIZE,"offset":offset}
        r=requests.get(url,headers=headers(sb_key),params=p,timeout=120)
        if not r.ok: raise RuntimeError(f"Supabase read {ticker} HTTP {r.status_code}: {r.text[:800]}")
        rows=r.json(); out.extend(rows)
        if len(rows)<DB_PAGE_SIZE: break
        offset += DB_PAGE_SIZE
    clean=[]
    for x in out:
        row={"ticker":ticker,"trade_date":str(x.get("trade_date",""))[:10],
             "open":fnum(x.get("open")),"high":fnum(x.get("high")),
             "low":fnum(x.get("low")),"close":fnum(x.get("close")),"volume":x.get("volume")}
        if row["trade_date"] and all(row[k] is not None for k in ["open","high","low","close"]):
            clean.append(row)
    clean.sort(key=lambda z:z["trade_date"])
    return clean

def normalize_actions(payload):
    out=defaultdict(list)
    def add(ticker,item):
        if not isinstance(item,dict): return
        t=str(ticker or item.get("ticker") or item.get("symbol") or "").upper().strip()
        action=str(item.get("action") or item.get("type") or item.get("action_type") or "").lower().strip()
        date=str(item.get("date") or item.get("ex_date") or item.get("event_date") or "")[:10]
        value=fnum(item.get("value") if item.get("value") is not None else item.get("ratio"))
        if t in TICKERS and action in {"split","dividend"} and date and value is not None:
            out[t].append({"date":date,"action":action,"value":value})
    if isinstance(payload,list):
        for item in payload: add(None,item)
    elif isinstance(payload,dict):
        if isinstance(payload.get("data"),list):
            for item in payload["data"]: add(None,item)
        for key,block in payload.items():
            if key in {"data","metadata","meta","status"}: continue
            if isinstance(block,dict) and isinstance(block.get("data"),list):
                for item in block["data"]: add(key,item)
            elif isinstance(block,list):
                for item in block: add(key,item)
            elif isinstance(block,dict):
                add(key,block)
    for t in list(out):
        seen=set(); cleaned=[]
        for x in sorted(out[t], key=lambda z:(z["date"],z["action"],z["value"])):
            sig=(x["date"],x["action"],x["value"])
            if sig not in seen: cleaned.append(x); seen.add(sig)
        out[t]=cleaned
    return dict(out)

def fetch_actions(api_key):
    params={"ticker":",".join(TICKERS),"period":"10y","api_key":api_key}
    print("📥 ONE batched corporate-actions request for all 122 symbols", flush=True)
    r=requests.get(BQ_CORP_URL,params=params,timeout=180)
    if r.status_code==404:
        print("ℹ️ HTTP 404 -> no corporate actions returned.", flush=True)
        return {}
    if r.status_code==429:
        raise RuntimeError(f"Business Quant rate limit: {r.text[:800]}")
    if not r.ok:
        raise RuntimeError(f"Business Quant HTTP {r.status_code}: {r.text[:1200]}")
    return normalize_actions(r.json())

def build_adjusted(raw,actions):
    if not raw: return []
    by_date={r["trade_date"]:r for r in raw}
    dates=[r["trade_date"] for r in raw]
    factors={d:1.0 for d in dates}
    for a in sorted(actions,key=lambda z:z["date"]):
        adate=a["date"]; val=fnum(a["value"])
        if val is None or val<=0: continue
        if a["action"]=="split":
            mult=1.0/val
        else:
            prev=[d for d in dates if d<adate]
            if not prev: continue
            pc=fnum(by_date[prev[-1]]["close"])
            if pc is None or pc<=0: continue
            mult=(pc-val)/pc
            if not (0<mult<=1): continue
        for d in dates:
            if d<adate: factors[d] *= mult
    out=[]
    for r in raw:
        f=factors[r["trade_date"]]
        out.append({"ticker":r["ticker"],"trade_date":r["trade_date"],
                    "adj_open":round(r["open"]*f,10),"adj_high":round(r["high"]*f,10),
                    "adj_low":round(r["low"]*f,10),"adj_close":round(r["close"]*f,10),
                    "adj_factor":round(f,12)})
    return out

def upsert(sb_url,sb_key,rows):
    url=f"{sb_url.rstrip('/')}/rest/v1/stock_daily"
    h=headers(sb_key); h["Prefer"]="resolution=merge-duplicates,return=minimal"
    for i in range(0,len(rows),DB_WRITE_BATCH):
        b=rows[i:i+DB_WRITE_BATCH]
        r=requests.post(url,params={"on_conflict":"ticker,trade_date"},headers=h,json=b,timeout=180)
        if not r.ok: raise RuntimeError(f"Supabase upsert HTTP {r.status_code}: {r.text[:1200]}")

def main():
    if len(TICKERS)!=122 or len(set(TICKERS))!=122: fail("122-symbol universe validation failed")
    bq=env("BUSINESSQUANT_API_KEY"); sb_url=env("SUPABASE_URL"); sb_key=env("SUPABASE_SERVICE_ROLE_KEY")
    print("="*88)
    print("CMS A5.2R — ADJUST 122 EXISTING SUPABASE OHLC")
    print(datetime.now(NY).strftime("%Y-%m-%d %H:%M:%S %Z"))
    print("Raw OHLC preserved. Only adj_* fields are rebuilt.")
    print("="*88)
    amap=fetch_actions(bq)
    ok=0; check=0; total=0
    for i,t in enumerate(TICKERS,1):
        print(f"\n[{i:03d}/122] {t}", flush=True)
        raw=fetch_raw(sb_url,sb_key,t)
        if not raw:
            print("    ❌ no raw rows"); check+=1; continue
        acts=amap.get(t,[])
        adj=build_adjusted(raw,acts)
        upsert(sb_url,sb_key,adj)
        total += len(adj)
        splits=sum(1 for x in acts if x["action"]=="split")
        divs=sum(1 for x in acts if x["action"]=="dividend")
        print(f"    raw={len(raw)} adjusted={len(adj)} splits={splits} dividends={divs} latest={raw[-1]['trade_date']}")
        if len(adj)>=200: ok += 1
        else: check += 1
    print("\n"+"="*88)
    print("FINAL SUMMARY")
    print(f"OK (>=200 adjusted rows): {ok}/122")
    print(f"CHECK: {check}")
    print(f"Adjusted rows written: {total}")
    if ok==122:
        print("✅ 122/122 adjusted OHLC successfully stored in Supabase.")
        print("✅ Raw OHLC preserved. A5.2R logic unchanged.")
    else:
        fail(f"Adjustment validation incomplete: {ok}/122")

if __name__=="__main__":
    main()
