"""Utility earnings event study using the grid-demand nowcast."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402

from pdn import equities, event_study as es, plots  # noqa: E402
from pdn.config import ROOT  # noqa: E402

FIRST_QUARTER = "2022Q1"   # 2021 YoY growth is distorted by the 2020 COVID base

if __name__ == "__main__":
    lv = pd.read_csv(ROOT / "reports" / "monthly_levels.csv")
    lv["month"] = pd.PeriodIndex(lv["month"], freq="M")
    sig = es.company_signals(lv)
    sig = sig[sig["quarter"] >= pd.Period(FIRST_QUARTER, "Q")]
    px = equities.prices()
    ed = equities.earnings_dates()
    ev = es.event_returns(es.match_earnings(sig, ed), px)
    out = ev.assign(quarter=ev["quarter"].astype(str))
    out.to_csv(ROOT / "reports" / "events.csv", index=False, float_format="%.6f")
    print(f"events: {len(ev)}, firms {ev['ticker'].nunique()}, quarters {ev['quarter'].nunique()}, "
          f"median pre-window {ev['pre_days'].median():.0f} sessions")

    Y, X = ("car_pre", "car_ann", "car_post"), ("accel", "growth", "raw")
    res = pd.DataFrame([es.regress(ev, y, x) for y in Y for x in X])
    res.to_csv(ROOT / "reports" / "event_study_results.csv", index=False, float_format="%.4f")
    print(res.round(3).to_string(index=False))

    # Robustness: winsorized CARs, and dropping 2024Q4 (Jan 2025 LA wildfires
    # crashed EIX/PCG inside the pre-earnings window).
    no_fire = ev[ev["quarter"] != pd.Period("2024Q4", "Q")]
    rob = pd.concat([
        pd.DataFrame([es.regress(ev, y, "accel", winsor=0.01) for y in Y]).assign(variant="winsorized 1%"),
        pd.DataFrame([es.regress(no_fire, y, "accel") for y in Y]).assign(variant="excl. 2024Q4"),
    ])
    rob.to_csv(ROOT / "reports" / "event_study_robustness.csv", index=False, float_format="%.4f")
    print(rob.round(3).to_string(index=False))
    plots.coef_chart(res, "event_study_coefs.png")
    for y in ("car_pre", "car_ann", "car_post"):
        print(y); print(es.tercile_spread(ev, y, "accel").round(1).to_string())
