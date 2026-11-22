"""Historical hourly temperature from the Open-Meteo archive (ERA5-based, free, no key)."""
from __future__ import annotations

import time

import pandas as pd
import requests

from .config import BA_WEATHER, FIRST_YEAR, RAW

URL = "https://archive-api.open-meteo.com/v1/archive"


def _fetch_chunk(lat: float, lon: float, start: str, end: str) -> pd.Series:
    params = dict(latitude=lat, longitude=lon, start_date=start, end_date=end,
                  hourly="temperature_2m", timezone="UTC", temperature_unit="fahrenheit")
    err = None
    for attempt in range(6):
        try:
            r = requests.get(URL, params=params, timeout=120)
            if r.status_code == 200:
                h = r.json()["hourly"]
                return pd.Series(h["temperature_2m"], index=pd.to_datetime(h["time"]), dtype=float)
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = repr(e)
        time.sleep(min(2 ** attempt * 5, 120))
    raise RuntimeError(f"Open-Meteo failed for {lat},{lon} {start}..{end}: {err}")


def _fetch_point(lat: float, lon: float, start: str, end: str) -> pd.Series:
    """Fetch one point year by year, caching each point on disk."""
    cache = RAW / "weather_points" / f"{lat:.2f}_{lon:.2f}.parquet"
    if cache.exists():
        s = pd.read_parquet(cache)["temp_f"]
        if str(s.index.max().date()) >= end:
            return s
    cache.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    y0, y1 = int(start[:4]), int(end[:4])
    for y in range(y0, y1 + 1):
        a = start if y == y0 else f"{y}-01-01"
        b = end if y == y1 else f"{y}-12-31"
        parts.append(_fetch_chunk(lat, lon, a, b))
        time.sleep(0.5)
    s = pd.concat(parts)
    s = s[~s.index.duplicated()]
    s.to_frame("temp_f").to_parquet(cache)
    return s


def download(end: str, force: bool = False) -> pd.DataFrame:
    """Population-weighted hourly temperature (deg F) per BA, UTC hour-beginning."""
    out = RAW / "weather_hourly.parquet"
    if out.exists() and not force:
        return pd.read_parquet(out)
    start = f"{FIRST_YEAR - 1}-12-25"
    frames = []
    cache = {}
    for ba, pts in BA_WEATHER.items():
        tot = sum(w for *_, w in pts)
        s = None
        for city, lat, lon, w in pts:
            key = (lat, lon)
            if key not in cache:
                cache[key] = _fetch_point(lat, lon, start, end)
                time.sleep(1)
            part = cache[key] * (w / tot)
            s = part if s is None else s.add(part, fill_value=0)
        frames.append(pd.DataFrame({"ba": ba, "utc_start": s.index, "temp_f": s.values}))
        print(f"  weather {ba}: {len(pts)} points")
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(out, index=False)
    return df
