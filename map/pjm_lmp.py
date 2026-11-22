"""PJM day-ahead LMPs for the Dominion zone: where congestion binds.

Two outputs (map/):
  pjm_dom_zone_daily.csv   daily average day-ahead LMP and its congestion
                           component for the DOMINION zone pricing point and
                           the PJM-wide reference (PJM-RTO), last ~2 years.
  pjm_dom_bus_congestion.csv  average day-ahead congestion component per
                           Dominion-zone bus over the last N days, plus the
                           share of hours with congestion above $5/MWh.

Source: PJM Data Miner 2 API (feed da_hrl_lmps). Needs a free subscription
key from https://apiportal.pjm.com in the PJM_API_KEY environment variable.
In this repo it runs in the `fetch-pjm-lmp` GitHub Action with the key stored
as a repository secret, so the key never touches the code.

PJM does not publish bus coordinates. build_map.py places a bus only when
its name matches an inferred substation name, and labels those as approximate.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "map"
API = "https://api.pjm.com/api/v1/da_hrl_lmps"
FIELDS = ("datetime_beginning_ept,pnode_id,pnode_name,type,zone,"
          "total_lmp_da,congestion_price_da,marginal_loss_price_da")
PAGE = 50_000
BUS_DAYS = int(os.environ.get("PJM_BUS_DAYS", "30"))
ZONE_DAYS = int(os.environ.get("PJM_ZONE_DAYS", "730"))


def _range(d0: date, d1: date) -> str:
    return f"{d0:%m/%d/%Y} 00:00to{d1:%m/%d/%Y} 23:59"


def fetch(params: dict, key: str) -> pd.DataFrame:
    rows, start = [], 1
    headers = {"Ocp-Apim-Subscription-Key": key}
    while True:
        p = dict(params, rowCount=PAGE, startRow=start, fields=FIELDS, format="json")
        for attempt in range(5):
            r = requests.get(API, params=p, headers=headers, timeout=120)
            if r.status_code == 429:  # PJM rate limit: wait and retry
                time.sleep(15 * (attempt + 1))
                continue
            r.raise_for_status()
            break
        else:
            r.raise_for_status()
        js = r.json()
        items = js.get("items", js if isinstance(js, list) else [])
        rows.extend(items)
        total = js.get("totalRows", len(items)) if isinstance(js, dict) else len(items)
        print(f"  {params.get('pnode_name') or params.get('zone')}: {len(rows):,}/{total:,}")
        if len(items) < PAGE or len(rows) >= total:
            break
        start += PAGE
        time.sleep(1)
    return pd.DataFrame(rows)


def zone_daily(key: str) -> pd.DataFrame:
    end = date.today()
    frames = []
    for name in ("DOMINION", "PJM-RTO"):
        # Chunk by ~90 days to keep each request small.
        d0 = end - timedelta(days=ZONE_DAYS)
        while d0 <= end:
            d1 = min(d0 + timedelta(days=89), end)
            frames.append(fetch({"pnode_name": name, "row_is_current": "TRUE",
                                 "datetime_beginning_ept": _range(d0, d1)}, key))
            d0 = d1 + timedelta(days=1)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["datetime_beginning_ept"]).dt.normalize()
    out = (df.groupby(["date", "pnode_name"])[["total_lmp_da", "congestion_price_da"]]
             .mean().unstack("pnode_name"))
    out.columns = [f"{a}_{b.lower().replace('-', '_')}" for a, b in out.columns]
    return out.reset_index()


def bus_congestion(key: str) -> pd.DataFrame:
    end = date.today()
    d0 = end - timedelta(days=BUS_DAYS)
    df = fetch({"zone": "DOMINION", "type": "BUS", "row_is_current": "TRUE",
                "datetime_beginning_ept": _range(d0, end)}, key)
    g = df.groupby(["pnode_id", "pnode_name"])
    out = pd.DataFrame({
        "avg_lmp": g["total_lmp_da"].mean(),
        "avg_congestion": g["congestion_price_da"].mean(),
        "p95_congestion": g["congestion_price_da"].quantile(0.95),
        "share_hours_congested": g["congestion_price_da"].apply(lambda s: (s > 5).mean()),
        "hours": g.size(),
    }).reset_index()
    out["window"] = f"{d0} to {end}"
    return out.sort_values("avg_congestion", ascending=False)


def main() -> None:
    key = os.environ.get("PJM_API_KEY")
    if not key:
        sys.exit("PJM_API_KEY is not set (free key: https://apiportal.pjm.com)")
    bus = bus_congestion(key)
    bus.to_csv(OUT / "pjm_dom_bus_congestion.csv", index=False, float_format="%.3f")
    print(f"buses: {len(bus)}")
    z = zone_daily(key)
    z.to_csv(OUT / "pjm_dom_zone_daily.csv", index=False, float_format="%.3f")
    print(f"zone days: {len(z)}")


if __name__ == "__main__":
    main()
