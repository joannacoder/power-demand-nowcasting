"""Build the daily panel, fit the point-in-time weather model, write results and figures."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd  # noqa: E402

from pdn import eia930, features, model, plots, subregion  # noqa: E402
from pdn.config import PROCESSED, ROOT  # noqa: E402

if __name__ == "__main__":
    PROCESSED.mkdir(parents=True, exist_ok=True)
    hourly = pd.concat([eia930.load(), subregion.load()], ignore_index=True)
    wx = pd.read_parquet(ROOT / "data/raw/weather_hourly.parquet")
    panel = features.build_panel(hourly, wx)
    # Weather data lags real time by a few days; drop days without it.
    panel.to_parquet(PROCESSED / "daily_panel.parquet", index=False)
    print(f"panel: {len(panel):,} BA-days, {panel['ba'].nunique()} BAs, "
          f"{panel['date'].min().date()} to {panel['date'].max().date()}")

    levels = model.monthly_levels(panel)
    out = levels.assign(month=levels["month"].astype(str))
    out.to_csv(ROOT / "reports" / "monthly_levels.csv", index=False, float_format="%.5f")

    acc = levels.groupby("ba").agg(
        daily_mape_model=("mape_model", "mean"),
        daily_mape_operator_dayahead=("mape_ba_dayahead", "mean"),
        monthly_abs_err_model=("month_err", lambda x: x.abs().mean()),
        months=("month_err", "count"),
    )
    acc[acc.columns[:3]] = acc[acc.columns[:3]].mul(100).round(2)
    acc.to_csv(ROOT / "reports" / "accuracy_by_ba.csv")
    print(acc.to_string())

    plots.growth_lines(levels, ["ERCO", "PJM", "MISO", "CISO"], "growth_isos.png",
                       "Underlying electricity demand growth in the largest US grids")
    plots.raw_vs_normalized(levels, "ERCO", "ercot_raw_vs_normalized.png")
    g = plots.latest_bar(levels, "growth_latest_by_ba.png")
    print(g.round(2).to_string())
