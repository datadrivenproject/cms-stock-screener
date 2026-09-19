#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared CMS universe: S&P Composite 1500 plus CMS core names."""

import io

import pandas as pd
import requests


WIKIMEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "CMSStockScreener/1.0 (github.com/datadrivenproject/cms-stock-screener)"

INDEX_PAGES = {
    "S&P 500": ("List_of_S&P_500_companies", 450),
    "S&P 400": ("List_of_S&P_400_companies", 380),
    "S&P 600": ("List_of_S&P_600_companies", 570),
}

SP500_CSV_FALLBACKS = [
    "https://raw.githubusercontent.com/chinobing/historical_sp500_constituents/refs/heads/main/sp500_constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
]

CORE_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX", "ORCL", "IBM", "DELL", "HPE", "SMCI",
    "CRM", "ADBE", "NOW", "PLTR", "PATH", "CRWD", "PANW", "FTNT", "DDOG", "NET", "SNOW", "MDB", "ZS", "OKTA", "TEAM",
    "QCOM", "MU", "INTC", "ARM", "MRVL", "AMAT", "LRCX", "KLAC", "ON", "MCHP",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "PYPL", "COIN", "HOOD", "SOFI", "XYZ", "NU", "IBKR",
    "LLY", "UNH", "ABBV", "MRK", "AMGN", "JNJ", "PFE", "GILD", "ISRG", "TMO", "TEM", "VEEV", "REGN", "VRTX", "DXCM",
    "XOM", "CVX", "COP", "CAT", "GE", "BA", "RTX", "LMT", "ETN", "VRT", "PLUG", "FCX", "SLB", "FSLR", "CEG",
    "WMT", "COST", "HD", "DIS", "UBER", "ABNB", "DASH", "BKNG", "SHOP", "MELI", "RBLX", "SPOT", "ROKU", "DUOL", "RDDT",
    "CRCL", "APP", "RKLB", "ASTS", "IONQ", "RGTI", "SOUN", "HIMS", "CAVA", "CVNA",
]


def normalize_ticker(value):
    ticker = str(value).upper().strip().replace(".", "-")
    return ticker if ticker and ticker != "NAN" else ""


def _symbol_column(df):
    for column in df.columns:
        if str(column).strip().lower() in {"symbol", "ticker", "tickers"}:
            return column
    return None


def _extract_tickers(tables, minimum):
    for df in tables:
        symbol_col = _symbol_column(df)
        if symbol_col is None:
            continue
        tickers = [normalize_ticker(x) for x in df[symbol_col].tolist()]
        tickers = list(dict.fromkeys(x for x in tickers if x))
        if len(tickers) >= minimum:
            return tickers
    return []


def get_wikipedia_index_tickers(page, minimum):
    response = requests.get(
        WIKIMEDIA_API,
        params={
            "action": "parse",
            "page": page,
            "prop": "text",
            "format": "json",
            "formatversion": 2,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    html = response.json().get("parse", {}).get("text", "")
    if not html:
        raise RuntimeError(f"Wikimedia returned no table HTML for {page}")
    tickers = _extract_tickers(pd.read_html(io.StringIO(html)), minimum)
    if len(tickers) < minimum:
        raise RuntimeError(f"Invalid list for {page}: {len(tickers)} < {minimum}")
    return tickers


def get_sp500_fallback():
    for url in SP500_CSV_FALLBACKS:
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            response.raise_for_status()
            tickers = _extract_tickers(
                [pd.read_csv(io.StringIO(response.text))],
                INDEX_PAGES["S&P 500"][1],
            )
            if tickers:
                return tickers
        except Exception as exc:
            print(f"WARNING: S&P 500 fallback failed: {url}: {exc}")
    return []


def get_index_tickers(index_name):
    page, minimum = INDEX_PAGES[index_name]
    try:
        return get_wikipedia_index_tickers(page, minimum)
    except Exception as exc:
        print(f"WARNING: {index_name} Wikimedia source failed: {exc}")
        if index_name == "S&P 500":
            fallback = get_sp500_fallback()
            if fallback:
                return fallback
        raise RuntimeError(f"Unable to load a valid current {index_name} list") from exc


def build_universe(verbose=False):
    index_lists = {
        name: get_index_tickers(name)
        for name in ("S&P 500", "S&P 400", "S&P 600")
    }
    universe = list(dict.fromkeys(
        index_lists["S&P 500"]
        + index_lists["S&P 400"]
        + index_lists["S&P 600"]
        + CORE_UNIVERSE
    ))
    if len(universe) < 1450:
        raise RuntimeError(f"Composite universe unexpectedly small: {len(universe)}")
    if verbose:
        for name, tickers in index_lists.items():
            print(f"{name}: {len(tickers)}")
        print(f"CMS core/watchlist: {len(CORE_UNIVERSE)}")
        print(f"Deduplicated production universe: {len(universe)}")
    return universe
