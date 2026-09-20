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

from universe_1500 import build_universe as build_base_universe, normalize_ticker, USER_AGENT

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
