"""EIA-930 subregion (zone) demand, e.g. PJM's Dominion zone (DOM).

Adapted from map/dom_nowcast.py (grid map work). Same output schema as
eia930.load(), so zones flow through features.build_panel unchanged.
"""
from __future__ import annotations

import io
import time

import pandas as pd
import requests

from .config import FIRST_YEAR, RAW, ZONE_PARENT

URL = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_SUBREGION_{y}_{h}.csv"


def download(last_year: int, force: bool = False) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for y in range(FIRST_YEAR, last_year + 1):
        for h in ("Jan_Jun", "Jul_Dec"):
            out = RAW / f"eia930sub_{y}_{h}.parquet"
            # The current year's files keep growing; always refresh them.
            if out.exists() and not force and y < last_year:
                continue
            r = None
            for attempt in range(4):
                try:
                    r = requests.get(URL.format(y=y, h=h), timeout=300)
                    break
                except requests.RequestException:
                    time.sleep(2 ** attempt * 5)
            if r is None or r.status_code != 200 or not r.content.startswith(b'"Balancing'):
                print(f"  skip subregion {y} {h}")
                continue
            df = pd.read_csv(io.BytesIO(r.content), thousands=",", low_memory=False)
            keep = pd.Series(False, index=df.index)
            for zone, parent in ZONE_PARENT.items():
                keep |= (df["Balancing Authority"] == parent) & (df["Sub-Region"] == zone)
            df = df[keep]
            out_df = pd.DataFrame({
                "ba": df["Sub-Region"].values,
                "utc_end": pd.to_datetime(df["UTC Time at End of Hour"], format="mixed").values,
                "demand": pd.to_numeric(df["Demand (MW)"], errors="coerce").values,
            })
            out_df.to_parquet(out, index=False)
            print(f"  saved {out.name}: {len(out_df):,} rows")


def clean(h: pd.DataFrame) -> pd.DataFrame:
    """Subregion data has no EIA 'adjusted' series: drop non-positive hours and
    spikes outside 0.5x to 1.8x of a centered 7-day rolling median."""
    out = []
    for z, g in h.groupby("ba"):
        g = g.sort_values("utc_end").copy()
        g["demand"] = g["demand"].where(g["demand"] > 0)
        med = g["demand"].rolling(24 * 7, center=True, min_periods=24).median()
        g["demand"] = g["demand"].where((g["demand"] / med).between(0.5, 1.8))
        out.append(g)
    return pd.concat(out, ignore_index=True)


def load() -> pd.DataFrame:
    files = sorted(RAW.glob("eia930sub_*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.drop_duplicates(["ba", "utc_end"], keep="last")
    df = clean(df)
    df["demand_fcst"] = float("nan")
    return df.reset_index(drop=True)
