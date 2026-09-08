#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMS A5.2R — adjust 110 stocks + 12 benchmark ETFs from existing Supabase raw OHLC.
Uses ONE Business Quant corporate-actions request; preserves raw OHLC.
Writes adj_open, adj_high, adj_low, adj_close, adj_factor.
"""
import os, sys
import numpy as np
import pandas as pd
import requests

STOCK_UNIVERSE = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX', 'ORCL', 'IBM', 'DELL', 'HPE', 'SMCI', 'CRM', 'ADBE', 'NOW', 'PLTR', 'PATH', 'CRWD', 'PANW', 'FTNT', 'DDOG', 'NET', 'SNOW', 'MDB', 'ZS', 'OKTA', 'TEAM', 'QCOM', 'MU', 'INTC', 'ARM', 'MRVL', 'AMAT', 'LRCX', 'KLAC', 'ON', 'MCHP', 'JPM', 'BAC', 'WFC', 'GS', 'MS', 'V', 'MA', 'AXP', 'PYPL', 'COIN', 'HOOD', 'SOFI', 'XYZ', 'NU', 'IBKR', 'LLY', 'UNH', 'ABBV', 'MRK', 'AMGN', 'JNJ', 'PFE', 'GILD', 'ISRG', 'TMO', 'TEM', 'VEEV', 'REGN', 'VRTX', 'DXCM', 'XOM', 'CVX', 'COP', 'CAT', 'GE', 'BA', 'RTX', 'LMT', 'ETN', 'VRT', 'PLUG', 'FCX', 'SLB', 'FSLR', 'CEG', 'WMT', 'COST', 'HD', 'DIS', 'UBER', 'ABNB', 'DASH', 'BKNG', 'SHOP', 'MELI', 'RBLX', 'SPOT', 'ROKU', 'DUOL', 'RDDT', 'CRCL', 'APP', 'RKLB', 'ASTS', 'IONQ', 'RGTI', 'SOUN', 'HIMS', 'CAVA', 'CVNA']
BENCHMARK_TICKERS = ['SPY', 'XLK', 'XLV', 'XLF', 'XLY', 'XLP', 'XLI', 'XLE', 'XLB', 'XLU', 'XLRE', 'XLC']
UNIVERSE = STOCK_UNIVERSE + BENCHMARK_TICKERS
EXPECTED = len(UNIVERSE)

BQ_BASE = "https://data.businessquant.com"
S = requests.Session()

def env(name):
    v=os.environ.get(name,"").strip()
    if not v:
        print(f"❌ Missing secret: {name}"); sys.exit(2)
    return v

BQ_KEY=env("BUSINESSQUANT_API_KEY")
SB_URL=env("SUPABASE_URL").rstrip("/")
SB_KEY=env("SUPABASE_SERVICE_ROLE_KEY")

def sb_headers(count=False):
    h={"apikey":SB_KEY,"Authorization":f"Bearer {SB_KEY}"}
    if count: h["Prefer"]="count=exact"
    return h

def fetch_raw():
    url=f"{SB_URL}/rest/v1/stock_daily"
    ticker_filter="in.("+",".join(UNIVERSE)+")"
    rows=[]; start=0; size=1000
    while True:
        h=sb_headers(); h["Range"]=f"{start}-{start+size-1}"
        p={"select":"ticker,trade_date,open,high,low,close",
           "ticker":ticker_filter,"order":"ticker.asc,trade_date.asc"}
        r=S.get(url,headers=h,params=p,timeout=60)
        if r.status_code not in (200,206):
            raise RuntimeError(f"Supabase read HTTP {r.status_code}: {r.text[:500]}")
        b=r.json()
        if not b: break
        rows.extend(b); print(f"Supabase raw read: +{len(b)} | total={len(rows)}")
        if len(b)<size: break
        start+=size
    d=pd.DataFrame(rows)
    if d.empty: raise RuntimeError("No raw rows in Supabase")
    d["ticker"]=d["ticker"].astype(str).str.upper()
    d["trade_date"]=pd.to_datetime(d["trade_date"],errors="coerce").dt.normalize()
    for c in ["open","high","low","close"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    return d.dropna(subset=["ticker","trade_date","close"]).drop_duplicates(
        ["ticker","trade_date"],keep="last").sort_values(["ticker","trade_date"])

def fetch_actions():
    p={"ticker":",".join(UNIVERSE),"action":"dividend,split","period":"1y",
       "limit":10000,"page":1,"api_key":BQ_KEY}
    r=S.get(f"{BQ_BASE}/corporate_actions",params=p,timeout=60)
    if r.status_code==404:
        return pd.DataFrame(columns=["date","ticker","action","value","notes"])
    if r.status_code!=200:
        raise RuntimeError(f"BQ corporate-actions HTTP {r.status_code}: {r.text[:500]}")
    payload=r.json()
    data=payload.get("data",[]) if isinstance(payload,dict) else payload if isinstance(payload,list) else []
    if not data and isinstance(payload,dict):
        for v in payload.values():
            if isinstance(v,dict) and isinstance(v.get("data"),list): data.extend(v["data"])
    if not data: return pd.DataFrame(columns=["date","ticker","action","value","notes"])
    d=pd.DataFrame(data)
    for c in ["date","ticker","action","value","notes"]:
        if c not in d.columns: d[c]=np.nan
    d["ticker"]=d["ticker"].astype(str).str.upper()
    d["date"]=pd.to_datetime(d["date"],errors="coerce").dt.normalize()
    d["action"]=d["action"].astype(str).str.lower().str.strip()
    d["value"]=pd.to_numeric(d["value"],errors="coerce")
    d=d[d["ticker"].isin(UNIVERSE)&d["action"].isin(["dividend","split"])].dropna(subset=["date","ticker"])
    print(f"Business Quant corporate actions: {len(d)} rows in ONE request")
    return d.sort_values(["ticker","date"])

def adjust(raw, acts):
    o=raw.copy().sort_values("trade_date").reset_index(drop=True)
    o["adj_factor"]=1.0
    for _,a in acts.sort_values("date").iterrows():
        prior=o["trade_date"]<a["date"]
        if not prior.any(): continue
        f=np.nan; v=a["value"]; typ=str(a["action"]).lower()
        if typ=="split" and pd.notna(v) and float(v)>0:
            f=1.0/float(v)
        elif typ=="dividend" and pd.notna(v) and float(v)>=0:
            prev=o.loc[prior,"close"].dropna()
            if not prev.empty:
                pc=float(prev.iloc[-1]); dv=float(v)
                if pc>0 and dv<pc: f=(pc-dv)/pc
        if pd.notna(f) and f>0: o.loc[prior,"adj_factor"]*=float(f)
    for c in ["open","high","low","close"]: o["adj_"+c]=o[c]*o["adj_factor"]
    return o

def num(x): return None if pd.isna(x) else float(x)

def upsert(rows):
    url=f"{SB_URL}/rest/v1/stock_daily?on_conflict=ticker,trade_date"
    h={"apikey":SB_KEY,"Authorization":f"Bearer {SB_KEY}","Content-Type":"application/json",
       "Prefer":"resolution=merge-duplicates,return=minimal"}
    for i in range(0,len(rows),500):
        b=rows[i:i+500]; r=S.post(url,headers=h,json=b,timeout=60)
        if r.status_code not in (200,201,204):
            raise RuntimeError(f"Supabase upsert HTTP {r.status_code}: {r.text[:500]}")
        print(f"Supabase write batch {i//500+1}: {len(b)} | HTTP {r.status_code}")

def verify():
    result=[]
    url=f"{SB_URL}/rest/v1/stock_daily"
    for t in UNIVERSE:
        h=sb_headers(True); h["Range"]="0-0"
        p={"select":"ticker","ticker":f"eq.{t}","adj_close":"not.is.null"}
        r=S.get(url,headers=h,params=p,timeout=30)
        n=-1
        if r.status_code in (200,206):
            try: n=int(r.headers.get("Content-Range","").split("/")[-1])
            except: pass
        result.append({"ticker":t,"adjusted_rows":n})
    return pd.DataFrame(result)

def main():
    print(f"CMS A5.2R adjusted data | {len(STOCK_UNIVERSE)} stocks + {len(BENCHMARK_TICKERS)} ETFs = {EXPECTED}")
    raw=fetch_raw()
    present=set(raw["ticker"].unique())
    missing=[t for t in UNIVERSE if t not in present]
    if missing:
        print("❌ Missing raw symbols in Supabase:",", ".join(missing)); sys.exit(1)

    acts=fetch_actions()
    rows=[]; status=[]
    for i,t in enumerate(UNIVERSE,1):
        r=raw[raw["ticker"]==t].copy()
        a=acts[acts["ticker"]==t].copy()
        z=adjust(r,a)
        for _,x in z.iterrows():
            rows.append({"ticker":t,"trade_date":x["trade_date"].date().isoformat(),
                         "adj_open":num(x["adj_open"]),"adj_high":num(x["adj_high"]),
                         "adj_low":num(x["adj_low"]),"adj_close":num(x["adj_close"]),
                         "adj_factor":num(x["adj_factor"])})
        status.append({"ticker":t,"raw_rows":len(r),"corporate_actions":len(a),
                       "min_adj_factor":float(z["adj_factor"].min()),
                       "max_adj_factor":float(z["adj_factor"].max())})
        print(f"[{i:03d}/{EXPECTED}] {t}: raw={len(r)} | actions={len(a)}")

    print(f"Prepared {len(rows)} adjusted rows.")
    upsert(rows)
    out=pd.DataFrame(status).merge(verify(),on="ticker",how="left")
    out["status"]=np.where(out["adjusted_rows"]>=200,"OK","CHECK")
    out.to_csv("adjust_122_status.csv",index=False,encoding="utf-8-sig")
    ok=int((out["status"]=="OK").sum())
    print("\n"+"="*80+"\nFINAL SUMMARY\n"+"="*80)
    print(f"OK (>=200 adjusted rows): {ok}/{EXPECTED}")
    print(f"CHECK: {EXPECTED-ok}")
    if ok!=EXPECTED:
        print(out[out["status"]!="OK"][["ticker","adjusted_rows"]].to_string(index=False)); sys.exit(1)
    print(f"✅ {EXPECTED}/{EXPECTED} adjusted OHLC successfully stored in Supabase.")
    print("✅ Raw OHLC preserved. A5.2R logic unchanged.")

if __name__=="__main__": main()
