"""Weather-normalized demand: a point-in-time monthly-level model.

For each balancing authority we fit, by OLS,

    log(MWh_d) = f(weather_d, calendar_d) + alpha_{month(d)} + e_d

where f is linear in heating/cooling degree days (with squares and one-day
lags), day of week and holidays, and alpha_m is a separate level for every
calendar month. alpha_m is the month's demand level after removing weather
and calendar effects, so

    weather-normalized YoY growth_m = exp(alpha_m - alpha_{m-12}) - 1.

Point-in-time: the weather/calendar coefficients used for month m are fit only
on data before month m starts (expanding window, refit monthly), then alpha_m
is the mean residual over month m. Nothing from month m or later leaks into f.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_TRAIN_DAYS = 365
HEAT_KNOTS = (35, 45, 55, 65)
COOL_KNOTS = (65, 72, 80, 88)


def _design(df: pd.DataFrame) -> pd.DataFrame:
    """Piecewise-linear temperature response plus calendar effects."""
    X = pd.DataFrame(index=df.index)
    t = df["tmean"]
    # Hinge functions let heating and cooling response bend (e.g. AC saturation).
    for k in HEAT_KNOTS:
        X[f"heat{k}"] = (k - t).clip(lower=0)
    for k in COOL_KNOTS:
        X[f"cool{k}"] = (t - k).clip(lower=0)
    X["tmax_hot"] = (df["tmax"] - 85).clip(lower=0)   # afternoon peaks
    X["tmin_cold"] = (40 - df["tmin"]).clip(lower=0)  # overnight heating
    X["hdd_l1"] = df["hdd_l1"]                        # thermal inertia
    X["cdd_l1"] = df["cdd_l1"]
    summer = df["date"].dt.month.isin([6, 7, 8, 9]).astype(float)
    X["cdd_summer"] = df["cdd"] * summer              # cooling response differs by season
    X["holiday"] = df["holiday"]
    for k in range(1, 7):
        X[f"dow{k}"] = (df["dow"] == k).astype(float)
    return X


def _fit(df: pd.DataFrame):
    """OLS with month fixed effects via within-month demeaning (Frisch-Waugh)."""
    X = _design(df)
    y = np.log(df["mwh"])
    g = df["month"]
    Xd = X - X.groupby(g).transform("mean")
    yd = y - y.groupby(g).transform("mean")
    beta, *_ = np.linalg.lstsq(Xd.values, yd.values, rcond=None)
    resid = yd.values - Xd.values @ beta
    # Robustness: drop gross outliers (bad EIA hours that survived cleaning) and refit once.
    keep = np.abs(resid) < 5 * np.std(resid)
    if (~keep).any():
        beta, *_ = np.linalg.lstsq(Xd.values[keep], yd.values[keep], rcond=None)
    return pd.Series(beta, index=X.columns)


def monthly_levels(panel: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time alpha_m per BA and month, plus diagnostics."""
    rows = []
    for ba, g in panel.groupby("ba"):
        g = g.sort_values("date").reset_index(drop=True)
        months = g["month"].unique()
        for m in months:
            train = g[g["month"] < m]
            test = g[g["month"] == m]
            if len(train) < MIN_TRAIN_DAYS or len(test) < 20:
                continue
            beta = _fit(train)
            fx = _design(test) @ beta
            r = np.log(test["mwh"]) - fx
            # Robust month level: median is less sensitive to a few bad EIA days.
            alpha = float(np.median(r))
            # Out-of-sample check: forecast this month's daily load from realized
            # weather and a level carried forward from information before month m:
            # alpha_hat = alpha_{m-12} + (alpha_{m-1} - alpha_{m-13})
            # (same month last year, plus the latest YoY change).
            r_tr = np.log(train["mwh"]) - _design(train) @ beta
            a_tr = r_tr.groupby(train["month"]).median()
            mape = mape_ba = month_err = np.nan
            if all(k in a_tr.index for k in (m - 1, m - 12, m - 13)):
                a_hat = a_tr[m - 12] + (a_tr[m - 1] - a_tr[m - 13])
                pred = np.exp(fx + a_hat)
                act = test["mwh"]
                mape = float(np.mean(np.abs(pred - act) / act))
                month_err = float(pred.mean() / act.mean() - 1)
                f = test["fcst_mwh"]
                ok = f.notna()
                if ok.sum() >= 20:
                    mape_ba = float(np.mean(np.abs(f[ok] - act[ok]) / act[ok]))
            rows.append(dict(ba=ba, month=m, alpha=alpha, n_days=len(test),
                             mwh_per_day=float(test["mwh"].mean()), cdd=float(test["cdd"].sum()),
                             hdd=float(test["hdd"].sum()),
                             mape_model=mape, mape_ba_dayahead=mape_ba,
                             month_err=month_err))
    out = pd.DataFrame(rows).sort_values(["ba", "month"])
    out["alpha_l12"] = out.groupby("ba")["alpha"].shift(12)
    # Only compare months that are exactly 12 apart (guards against gaps).
    gap = out["month"] - out.groupby("ba")["month"].shift(12)
    out["wn_yoy"] = np.where(gap.map(lambda x: getattr(x, "n", None)) == 12,
                             np.exp(out["alpha"] - out["alpha_l12"]) - 1, np.nan)
    mwh_l12 = out.groupby("ba")["mwh_per_day"].shift(12)
    out["raw_yoy"] = np.where(gap.map(lambda x: getattr(x, "n", None)) == 12,
                              out["mwh_per_day"] / mwh_l12 - 1, np.nan)
    return out.drop(columns="alpha_l12").reset_index(drop=True)
