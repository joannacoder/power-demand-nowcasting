"""Build a daily panel: local-day demand, weather degree days, calendar flags."""
from __future__ import annotations

import holidays
import numpy as np
import pandas as pd

from .config import BA_TZ

BASE_F = 65.0  # degree-day base temperature


def daily_demand(hourly: pd.DataFrame) -> pd.DataFrame:
    """Sum hourly MW to local-day MWh. Keep only complete, plausible days."""
    out = []
    for ba, g in hourly.groupby("ba"):
        g = g.copy()
        # EIA stamps hour-ending; shift back 1h so the hour belongs to its local day.
        local = (g["utc_end"] - pd.Timedelta(hours=1)).dt.tz_localize("UTC").dt.tz_convert(BA_TZ[ba])
        g["date"] = local.dt.tz_localize(None).dt.normalize()
        g["demand"] = g["demand"].where(g["demand"] > 0)
        g["demand_fcst"] = g["demand_fcst"].where(g["demand_fcst"] > 0)
        d = g.groupby("date").agg(
            n=("demand", "count"),
            mwh=("demand", "sum"),
            fcst_mwh=("demand_fcst", "sum"),
            n_fcst=("demand_fcst", "count"),
            peak_mw=("demand", "max"),
        )
        # DST days have 23/25 hours; scale to a 24h-equivalent daily energy.
        hrs = g.groupby("date").size()
        d = d[(d["n"] >= 23) & (d["n"] == hrs.reindex(d.index))]
        d["mwh"] = d["mwh"] * 24 / d["n"]
        d["fcst_mwh"] = np.where(d["n_fcst"] == d["n"], d["fcst_mwh"] * 24 / d["n"], np.nan)
        d["ba"] = ba
        out.append(d.reset_index())
    df = pd.concat(out, ignore_index=True)
    return df[["ba", "date", "mwh", "fcst_mwh", "peak_mw"]]


def daily_weather(hourly_w: pd.DataFrame) -> pd.DataFrame:
    out = []
    for ba, g in hourly_w.groupby("ba"):
        local = g["utc_start"].dt.tz_localize("UTC").dt.tz_convert(BA_TZ[ba])
        g = g.assign(date=local.dt.tz_localize(None).dt.normalize())
        d = g.groupby("date")["temp_f"].agg(["mean", "max", "min", "count"])
        d = d[d["count"] >= 23]
        hh = g.assign(hdh=(BASE_F - g["temp_f"]).clip(lower=0),
                      cdh=(g["temp_f"] - BASE_F).clip(lower=0)).groupby("date")[["hdh", "cdh"]].mean()
        d = d.join(hh)
        d = d.rename(columns={"mean": "tmean", "max": "tmax", "min": "tmin", "hdh": "hdd", "cdh": "cdd"})
        d["ba"] = ba
        out.append(d.drop(columns="count").reset_index())
    return pd.concat(out, ignore_index=True)


def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    years = range(df["date"].dt.year.min(), df["date"].dt.year.max() + 1)
    us_hol = holidays.US(years=years)
    df = df.copy()
    df["dow"] = df["date"].dt.dayofweek
    df["holiday"] = df["date"].dt.date.map(lambda x: x in us_hol).astype(int)
    df["month"] = df["date"].dt.to_period("M")
    return df


def build_panel(hourly: pd.DataFrame, hourly_w: pd.DataFrame) -> pd.DataFrame:
    dem = daily_demand(hourly)
    wx = daily_weather(hourly_w)
    df = dem.merge(wx, on=["ba", "date"], how="inner").sort_values(["ba", "date"])
    # Thermal inertia: yesterday's degree days matter for today's load.
    for c in ("hdd", "cdd"):
        df[f"{c}_l1"] = df.groupby("ba")[c].shift(1)
    df = add_calendar(df).dropna(subset=["hdd_l1", "cdd_l1"])
    return df.reset_index(drop=True)
