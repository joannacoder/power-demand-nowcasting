"""Weather-normalized nowcast for the Dominion (DOM) zone of PJM.

Links the grid map to the demand nowcast. Reuses the project's point-in-time
model (src/pdn/model.py) on EIA-930 *subregion* data, where PJM publishes
hourly demand for its transmission zones, including DOM.

Outputs (map/):
  dom_monthly.csv  month, weather-normalized YoY growth, peak MW, model error
  dom_daily.csv    day, actual MWh, weather-expected MWh, surprise %, peak MW

Usage:  python map/dom_nowcast.py
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pdn import features, model, weather  # noqa: E402
from pdn.config import RAW as PDN_RAW  # noqa: E402

RAW = ROOT / "data" / "raw" / "map"
OUT = ROOT / "map"
SUB_URL = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_SUBREGION_{y}_{h}.csv"
FIRST_YEAR = 2019
ZONE = "DOM"
TZ = "America/New_York"

# Weather points for the Dominion zone. Weights are rough load shares
# (Northern Virginia data centers + DC suburbs, Richmond, Hampton Roads):
# a documented modelling assumption, not ground truth.
DOM_WEATHER = [("Dulles/Ashburn", 38.95, -77.45, 0.45),
               ("Richmond", 37.54, -77.44, 0.30),
               ("Norfolk", 36.85, -76.29, 0.25)]


def download_zone(last_year: int) -> pd.DataFrame:
    out = RAW / "eia930_dom_hourly.parquet"
    RAW.mkdir(parents=True, exist_ok=True)
    frames = []
    for y in range(FIRST_YEAR, last_year + 1):
        for h in ("Jan_Jun", "Jul_Dec"):
            cache = RAW / f"eia930_sub_dom_{y}_{h}.parquet"
            if cache.exists() and not (y == last_year):
                frames.append(pd.read_parquet(cache))
                continue
            r = None
            for attempt in range(4):
                try:
                    r = requests.get(SUB_URL.format(y=y, h=h), timeout=300)
                    break
                except requests.RequestException:
                    time.sleep(2 ** attempt * 5)
            if r is None or r.status_code != 200 or not r.content.startswith(b'"Balancing'):
                print(f"  skip {y} {h}")
                continue
            df = pd.read_csv(io.BytesIO(r.content), thousands=",", low_memory=False)
            df = df[(df["Balancing Authority"] == "PJM") & (df["Sub-Region"] == ZONE)]
            df = pd.DataFrame({
                "utc_end": pd.to_datetime(df["UTC Time at End of Hour"], format="mixed"),
                "demand": pd.to_numeric(df["Demand (MW)"], errors="coerce")})
            df.to_parquet(cache, index=False)
            frames.append(df)
            print(f"  {y} {h}: {len(df):,} hours")
    hourly = pd.concat(frames, ignore_index=True).drop_duplicates("utc_end").sort_values("utc_end")
    hourly.to_parquet(out, index=False)
    return hourly


def zone_weather(end: str) -> pd.DataFrame:
    start = f"{FIRST_YEAR - 1}-12-25"
    tot = sum(w for *_, w in DOM_WEATHER)
    s = None
    for _, lat, lon, w in DOM_WEATHER:
        part = weather._fetch_point(lat, lon, start, end) * (w / tot)
        s = part if s is None else s.add(part, fill_value=0)
    return pd.DataFrame({"ba": ZONE, "utc_start": s.index, "temp_f": s.values})


def clean_hourly(h: pd.DataFrame) -> pd.DataFrame:
    """Drop zero/negative hours and spikes far from a rolling median."""
    h = h.copy()
    h["demand"] = h["demand"].where(h["demand"] > 0)
    med = h["demand"].rolling(24 * 7, center=True, min_periods=24).median()
    h["demand"] = h["demand"].where((h["demand"] / med).between(0.5, 1.8))
    return h


def daily_surprise(panel: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample daily forecast for each month, same rule as model.monthly_levels.

    For month m: fit weather/calendar coefficients on data before m, carry the
    level forward as alpha_{m-12} + (alpha_{m-1} - alpha_{m-13}), and compare
    the forecast with what actually happened. surprise > 0 means demand ran
    above what weather and the recent trend implied.
    """
    g = panel.sort_values("date").reset_index(drop=True)
    rows = []
    for m in g["month"].unique():
        train, test = g[g["month"] < m], g[g["month"] == m]
        if len(train) < model.MIN_TRAIN_DAYS:
            continue
        beta = model._fit(train)
        r_tr = np.log(train["mwh"]) - model._design(train) @ beta
        a = r_tr.groupby(train["month"]).median()
        if not all(k in a.index for k in (m - 1, m - 12, m - 13)):
            continue
        a_hat = a[m - 12] + (a[m - 1] - a[m - 13])
        exp_mwh = np.exp(model._design(test) @ beta + a_hat)
        rows.append(pd.DataFrame({"date": test["date"], "mwh": test["mwh"],
                                  "expected_mwh": exp_mwh, "peak_mw": test["peak_mw"],
                                  "tmean": test["tmean"]}))
    d = pd.concat(rows, ignore_index=True)
    d["surprise_pct"] = 100 * (d["mwh"] / d["expected_mwh"] - 1)
    return d


def main() -> None:
    today = pd.Timestamp.today()
    hourly = clean_hourly(download_zone(today.year))
    hourly["ba"] = ZONE
    hourly["demand_fcst"] = np.nan
    features.BA_TZ.setdefault(ZONE, TZ)  # DOM is a PJM zone, not in the BA table
    end = str(min(hourly["utc_end"].max().normalize(), today.normalize() - pd.Timedelta(days=6)).date())
    wx = zone_weather(end)
    panel = features.build_panel(hourly, wx)
    print(f"DOM panel: {len(panel):,} days, {panel['date'].min().date()} to {panel['date'].max().date()}")

    levels = model.monthly_levels(panel)
    peaks = panel.groupby("month")["peak_mw"].max()
    levels["peak_mw"] = levels["month"].map(peaks)
    levels.assign(month=levels["month"].astype(str)).to_csv(
        OUT / "dom_monthly.csv", index=False, float_format="%.5f")

    daily = daily_surprise(panel)
    daily.to_csv(OUT / "dom_daily.csv", index=False, float_format="%.3f")
    last = levels.dropna(subset=["wn_yoy"]).tail(6)
    print(last[["month", "wn_yoy", "raw_yoy", "peak_mw", "mape_model"]].to_string(index=False))
    print("daily surprise: mean abs %.2f%%" % daily["surprise_pct"].abs().mean())


if __name__ == "__main__":
    main()
