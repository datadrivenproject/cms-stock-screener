#!/usr/bin/env python3
import os, requests, json

URL="https://data.businessquant.com/quotes"
KEY=os.environ["BUSINESSQUANT_API_KEY"]
base={"ticker":"AAPL","from_date":"2026-09-18","till_date":"2026-09-18","limit":10,"page":1,"api_key":KEY}

for mode in ("eod","daily"):
    p={**base,"mode":mode}
    r=requests.get(URL,params=p,timeout=60)
    print("\n=== MODE:",mode,"HTTP:",r.status_code,"===")
    if not r.ok:
        print(r.text[:1000]); continue
    obj=r.json()
    data=obj.get("data",[]) if isinstance(obj,dict) else []
    print("rows:",len(data))
    print("dates:",[str(x.get("date",""))[:10] for x in data])
    if data:
        x=data[-1]
        print("last:",json.dumps({k:x.get(k) for k in ("date","open","high","low","close","volume")},ensure_ascii=False))
