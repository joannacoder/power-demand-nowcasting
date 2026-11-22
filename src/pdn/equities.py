"""Listed utilities, their grid exposure, daily prices and earnings dates.

Exposure weights are rough shares of each company's retail electric load by
balancing authority / zone, from company 10-K service-territory descriptions.
They are a documented modelling assumption, fixed over the sample.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from .config import RAW

EXPOSURE = {
    # ticker: {BA or zone: weight}
    "DUK":  {"DUK": 0.40, "CPLE": 0.25, "FPC": 0.20, "MISO": 0.10, "PJM": 0.05},
    "NEE":  {"FPL": 1.0},
    "SO":   {"SOCO": 1.0},
    "D":    {"DOM": 0.80, "SCEG": 0.20},
    "PNW":  {"AZPS": 1.0},
    "XEL":  {"MISO": 0.45, "PSCO": 0.35, "SWPP": 0.20},
    "IDA":  {"IPCO": 1.0},
    "POR":  {"PGE": 1.0},
    "PPL":  {"LGEE": 0.60, "PJM": 0.40},
    "TXNM": {"PNM": 0.50, "ERCO": 0.50},
    "CNP":  {"ERCO": 0.85, "MISO": 0.15},
    "AEP":  {"PJM": 0.55, "SWPP": 0.25, "ERCO": 0.20},
    "SRE":  {"ERCO": 0.50, "CISO": 0.50},
    "EXC":  {"PJM": 1.0},
    "PEG":  {"PJM": 1.0},
    "FE":   {"PJM": 1.0},
    "ETR":  {"MISO": 1.0},
    "AEE":  {"MISO": 1.0},
    "CMS":  {"MISO": 1.0},
    "DTE":  {"MISO": 1.0},
    "WEC":  {"MISO": 1.0},
    "LNT":  {"MISO": 1.0},
    "EVRG": {"SWPP": 1.0},
    "OGE":  {"SWPP": 1.0},
    "ED":   {"NYIS": 1.0},
    "ES":   {"ISNE": 1.0},
    "EIX":  {"CISO": 1.0},
    "PCG":  {"CISO": 1.0},
}
BENCHMARK = "XLU"   # Utilities Select Sector SPDR: sector-adjusted returns
MARKET = "SPY"

SEC_UA = {"User-Agent": "pdn-research-script/0.1"}


def prices(start: str = "2019-01-01", force: bool = False) -> pd.DataFrame:
    """Adjusted daily close (splits and dividends) from Yahoo Finance via yfinance."""
    out = RAW / "prices.parquet"
    if out.exists() and not force:
        return pd.read_parquet(out)
    import yfinance as yf
    tickers = list(EXPOSURE) + [BENCHMARK, MARKET]
    px = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px.to_parquet(out)
    return px


# SEC CIKs, verified against the "tickers" field of each EDGAR submissions file.
CIK = {
    "DUK": 1326160, "NEE": 753308, "SO": 92122, "D": 715957, "PNW": 764622,
    "XEL": 72903, "IDA": 1057877, "POR": 784977, "PPL": 922224, "TXNM": 1108426,
    "CNP": 1130310, "AEP": 4904, "SRE": 1032208, "EXC": 1109357, "PEG": 788784,
    "FE": 1031296, "ETR": 65984, "AEE": 1002910, "CMS": 811156, "DTE": 936340,
    "WEC": 783325, "LNT": 352541, "EVRG": 1711269, "OGE": 1021635, "ED": 1047862,
    "ES": 72741, "EIX": 827052, "PCG": 1004980,
}


def _filings(cik: int) -> pd.DataFrame:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    r = requests.get(url, headers=SEC_UA, timeout=60)
    r.raise_for_status()
    j = r.json()
    frames = [pd.DataFrame(j["filings"]["recent"])]
    for f in j["filings"].get("files", []):   # older filings live in extra pages
        time.sleep(0.2)
        rr = requests.get(f"https://data.sec.gov/submissions/{f['name']}", headers=SEC_UA, timeout=60)
        if rr.ok:
            frames.append(pd.DataFrame(rr.json()))
    return pd.concat(frames, ignore_index=True)


def earnings_dates(force: bool = False) -> pd.DataFrame:
    """Earnings announcement dates = 8-K filings carrying Item 2.02
    (Results of Operations and Financial Condition), from SEC EDGAR.

    acceptanceDateTime tells us whether the filing landed before or after the
    close: after 16:00 ET, the first trading reaction is the next day.
    """
    out = RAW / "earnings_dates.parquet"
    if out.exists() and not force:
        return pd.read_parquet(out)
    rows = []
    for t in EXPOSURE:
        f = _filings(CIK[t])
        f = f[(f["form"] == "8-K") & f["items"].fillna("").str.contains("2.02")]
        acc = pd.to_datetime(f["acceptanceDateTime"].str.slice(0, 19))  # EDGAR stamps ET
        d = pd.DataFrame({"ticker": t, "filing_date": pd.to_datetime(f["filingDate"]),
                          "accepted": acc})
        rows.append(d)
        time.sleep(0.2)
    df = pd.concat(rows, ignore_index=True).drop_duplicates(["ticker", "filing_date"])
    df = df[df["filing_date"] >= "2019-01-01"].sort_values(["ticker", "filing_date"])
    df.to_parquet(out, index=False)
    return df.reset_index(drop=True)
