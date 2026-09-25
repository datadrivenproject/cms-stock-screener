#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Expanded CMS universe for one-time bootstrap.

Keeps the locked production S&P Composite 1500 + CMS core intact and appends
current U.S. equity holdings from iShares Russell 3000 ETF (IWV), in fund
weight order. This module is intentionally used by bootstrap first; production
A logic is not changed.
"""

import io
import pandas as pd
import requests

import io as _io

WIKIMEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "CMSStockScreener/1.0 (github.com/datadrivenproject/cms-stock-screener)"
INDEX_PAGES = {
    "S&P 500": ("List_of_S&P_500_companies", 450),
    "S&P 400": ("List_of_S&P_400_companies", 380),
    "S&P 600": ("List_of_S&P_600_companies", 570),
}
CORE_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","ORCL","IBM","DELL","HPE","SMCI",
    "CRM","ADBE","NOW","PLTR","PATH","CRWD","PANW","FTNT","DDOG","NET","SNOW","MDB","ZS","OKTA","TEAM",
    "QCOM","MU","INTC","ARM","MRVL","AMAT","LRCX","KLAC","ON","MCHP","JPM","BAC","WFC","GS","MS","V","MA","AXP",
    "PYPL","COIN","HOOD","SOFI","XYZ","NU","IBKR","LLY","UNH","ABBV","MRK","AMGN","JNJ","PFE","GILD","ISRG","TMO",
    "TEM","VEEV","REGN","VRTX","DXCM","XOM","CVX","COP","CAT","GE","BA","RTX","LMT","ETN","VRT","PLUG","FCX","SLB",
    "FSLR","CEG","WMT","COST","HD","DIS","UBER","ABNB","DASH","BKNG","SHOP","MELI","RBLX","SPOT","ROKU","DUOL","RDDT",
    "CRCL","APP","RKLB","ASTS","IONQ","RGTI","SOUN","HIMS","CAVA","CVNA"
]
def normalize_ticker(value):
    ticker=str(value).upper().strip().replace(".","-")
    return ticker if ticker and ticker!="NAN" else ""
def _extract(tables, minimum):
    for df in tables:
        col=next((c for c in df.columns if str(c).strip().lower() in {"symbol","ticker","tickers"}),None)
        if col is not None:
            xs=list(dict.fromkeys(normalize_ticker(x) for x in df[col].tolist()))
            xs=[x for x in xs if x]
            if len(xs)>=minimum: return xs
    return []
def _index(name):
    page,minimum=INDEX_PAGES[name]
    r=requests.get(WIKIMEDIA_API,params={"action":"parse","page":page,"prop":"text","format":"json","formatversion":2},
                   headers={"User-Agent":USER_AGENT},timeout=60)
    r.raise_for_status()
    xs=_extract(pd.read_html(_io.StringIO(r.json()["parse"]["text"])),minimum)
    if len(xs)<minimum: raise RuntimeError(f"Invalid {name} list: {len(xs)}")
    return xs
def build_base_universe(verbose=False):
    lists={n:_index(n) for n in ("S&P 500","S&P 400","S&P 600")}
    base=list(dict.fromkeys(lists["S&P 500"]+lists["S&P 400"]+lists["S&P 600"]+CORE_UNIVERSE))
    if len(base)<1450: raise RuntimeError(f"Base universe unexpectedly small: {len(base)}")
    return base

IWV_HOLDINGS_CSV = (
    "https://www.blackrock.com/us/individual/products/239714/"
    "ishares-russell-3000-etf/latest-holdings.csv"
)
TARGET_UNIVERSE_SIZE = 2500


def get_iwv_equity_tickers():
    response = requests.get(IWV_HOLDINGS_CSV, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text), skiprows=8)
    required = {"Ticker", "Asset Class", "Location"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"Unexpected IWV holdings columns: {list(df.columns)}")
    df = df[
        df["Asset Class"].astype(str).str.strip().eq("Equity")
        & df["Location"].astype(str).str.strip().eq("United States")
    ]
    tickers = []
    for raw in df["Ticker"].tolist():
        # BlackRock uses spaces for share classes (e.g. BRK B); BQ convention uses '-'.
        ticker = normalize_ticker(str(raw).replace(" ", "-"))
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    if len(tickers) < 2000:
        raise RuntimeError(f"IWV equity list unexpectedly small: {len(tickers)}")
    return tickers


def build_universe(verbose=False):
    base = build_base_universe(verbose=False)
    iwv = get_iwv_equity_tickers()
    universe = list(base)
    for ticker in iwv:
        if ticker not in universe:
            universe.append(ticker)
        if len(universe) >= TARGET_UNIVERSE_SIZE:
            break
    if len(universe) < TARGET_UNIVERSE_SIZE:
        raise RuntimeError(f"Expanded universe unexpectedly small: {len(universe)}")
    if verbose:
        print(f"Locked base universe: {len(base)}")
        print(f"Current IWV U.S. equity holdings available: {len(iwv)}")
        print(f"Expanded bootstrap universe: {len(universe)}")
        print(f"New names appended: {len(universe) - len(base)}")
    return universe
