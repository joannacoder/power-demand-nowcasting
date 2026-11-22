"""Download and tidy EIA-930 hourly balancing-authority data.

Source: EIA Hourly Electric Grid Monitor six-month bulk files
https://www.eia.gov/electricity/gridmonitor/ (no API key needed).
"""
from __future__ import annotations

import io
import time

import pandas as pd
import requests

from .config import BAS, FIRST_YEAR, RAW

BASE = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{y}_{h}.csv"

COLS = {
    "Balancing Authority": "ba",
    "UTC Time at End of Hour": "utc_end",
    "Demand Forecast (MW)": "demand_fcst",
    "Demand (MW)": "demand_raw",
    "Demand (MW) (Adjusted)": "demand",
}


def _periods(last_year: int):
    for y in range(FIRST_YEAR, last_year + 1):
        for h in ("Jan_Jun", "Jul_Dec"):
            yield y, h


def download(last_year: int, force: bool = False) -> list:
    """Fetch each six-month file, keep our BAs and core columns, save parquet."""
    RAW.mkdir(parents=True, exist_ok=True)
    saved = []
    for y, h in _periods(last_year):
        out = RAW / f"eia930_{y}_{h}.parquet"
        if out.exists() and not force:
            saved.append(out)
            continue
        url = BASE.format(y=y, h=h)
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=300)
                break
            except requests.RequestException:
                time.sleep(2 ** attempt * 5)
        else:
            print(f"  failed {url}")
            continue
        if r.status_code != 200 or not r.content.startswith(b'"Balancing'):
            print(f"  skip {y} {h}: HTTP {r.status_code}")
            continue
        df = pd.read_csv(io.BytesIO(r.content), usecols=lambda c: c in COLS,
                         thousands=",", low_memory=False)
        df = df.rename(columns=COLS)
        df = df[df["ba"].isin(BAS)]
        df["utc_end"] = pd.to_datetime(df["utc_end"], format="mixed")
        for c in ("demand_fcst", "demand_raw", "demand"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df.to_parquet(out, index=False)
        print(f"  saved {out.name}: {len(df):,} rows")
        saved.append(out)
    return saved


def load() -> pd.DataFrame:
    files = sorted(RAW.glob("eia930_*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.drop_duplicates(["ba", "utc_end"], keep="last").sort_values(["ba", "utc_end"])
    return df.reset_index(drop=True)
