"""Do grid-demand nowcasts carry information about utility stocks around earnings?

Signal (per company i, fiscal quarter q):
  growth_iq  = exposure-weighted mean of monthly weather-normalized YoY demand
               growth over the quarter's three months (from monthly_levels).
  accel_iq   = growth_iq - mean(growth_i,q-4..q-1): has underlying demand
               growth sped up or slowed vs the past year? This is the "surprise"
               candidate, since the market already knows the trend.

Timing (no look-ahead):
  * EIA-930 hourly data are public with about a one-day lag and the weather
    archive about five days, so the quarter's signal is knowable by
    quarter end + 7 calendar days ("signal date").
  * Earnings date = the first SEC 8-K with Item 2.02 filed 14 to 80 days after
    quarter end. Event day 0 = first trading session at or after the filing's
    acceptance time (after 16:00 ET -> next session).

Returns: daily log returns in excess of beta x XLU (utilities ETF), beta from
trading days [-250, -30] before each event (min 120 obs).
  * CAR[-1,+1]      announcement reaction
  * CAR[sig, -2]    pre-announcement drift, from the first session after the
                    signal date to two sessions before day 0 (tradable)
  * CAR[+2, +40]    post-announcement drift
Tests: pooled OLS of CAR on the cross-sectionally standardized signal with
quarter fixed effects and standard errors clustered by quarter (only ~28 firms,
so clustering by quarter is the conservative choice for common shocks).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from .equities import BENCHMARK, EXPOSURE

SIGNAL_LAG_DAYS = 7


def company_signals(levels: pd.DataFrame) -> pd.DataFrame:
    lv = levels.copy()
    lv["quarter"] = lv["month"].dt.asfreq("Q")
    q = (lv.groupby(["ba", "quarter"])
           .agg(growth=("wn_yoy", "mean"), raw=("raw_yoy", "mean"), n=("wn_yoy", "count"))
           .reset_index())
    q = q[q["n"] == 3]
    rows = []
    for t, w in EXPOSURE.items():
        sub = q[q["ba"].isin(w)].copy()
        sub["w"] = sub["ba"].map(w)
        # Require every exposure region to be present that quarter.
        g = sub.groupby("quarter").filter(lambda x: len(x) == len(w))
        g = g.groupby("quarter").apply(
            lambda x: pd.Series({"growth": np.average(x["growth"], weights=x["w"]),
                                 "raw": np.average(x["raw"], weights=x["w"])}),
            include_groups=False)
        g["ticker"] = t
        rows.append(g.reset_index())
    s = pd.concat(rows, ignore_index=True).sort_values(["ticker", "quarter"])
    trail = s.groupby("ticker")["growth"].transform(lambda x: x.shift(1).rolling(4, min_periods=4).mean())
    s["accel"] = s["growth"] - trail
    s["quarter_end"] = s["quarter"].dt.end_time.dt.normalize()
    s["signal_date"] = s["quarter_end"] + pd.Timedelta(days=SIGNAL_LAG_DAYS)
    return s.reset_index(drop=True)


def match_earnings(sig: pd.DataFrame, ed: pd.DataFrame) -> pd.DataFrame:
    ed = ed.copy()
    # EDGAR acceptanceDateTime is UTC; convert to US/Eastern.
    ed["accepted_et"] = (ed["accepted"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
                         .dt.tz_localize(None))
    out = []
    for _, r in sig.iterrows():
        e = ed[(ed["ticker"] == r["ticker"])
               & (ed["accepted_et"] >= r["quarter_end"] + pd.Timedelta(days=14))
               & (ed["accepted_et"] <= r["quarter_end"] + pd.Timedelta(days=80))]
        if len(e):
            out.append({**r.to_dict(), "accepted_et": e["accepted_et"].min()})
    return pd.DataFrame(out)


def _abnormal(px: pd.DataFrame) -> pd.DataFrame:
    return np.log(px).diff()


def event_returns(events: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    r = _abnormal(px)
    days = r.index
    out = []
    for _, e in events.iterrows():
        t = e["ticker"]
        if t not in r:
            continue
        a = e["accepted_et"]
        day0_cal = a.normalize() + (pd.Timedelta(days=1) if a.hour >= 16 else pd.Timedelta(0))
        i0 = days.searchsorted(day0_cal)
        isig = days.searchsorted(e["signal_date"] + pd.Timedelta(days=1))
        if i0 + 1 >= len(days) or i0 - 250 < 0:
            continue
        est = slice(i0 - 250, i0 - 30)
        y, x = r[t].iloc[est], r[BENCHMARK].iloc[est]
        ok = y.notna() & x.notna()
        if ok.sum() < 120:
            continue
        beta = np.cov(y[ok], x[ok])[0, 1] / np.var(x[ok], ddof=1)
        ar = r[t] - beta * r[BENCHMARK]
        car_ann = ar.iloc[i0 - 1:i0 + 2].sum()
        car_pre = ar.iloc[isig:i0 - 1].sum() if i0 - 1 > isig else np.nan
        # Post-announcement drift; only for events with the full window observed.
        car_post = ar.iloc[i0 + 2:i0 + 41].sum() if i0 + 41 <= len(days) else np.nan
        out.append({**e.to_dict(), "day0": days[i0], "beta": beta,
                    "car_ann": car_ann, "car_pre": car_pre, "car_post": car_post,
                    "pre_days": max(i0 - 1 - isig, 0)})
    return pd.DataFrame(out)


def regress(ev: pd.DataFrame, y: str, x: str, winsor: float | None = None) -> dict:
    d = ev.dropna(subset=[y, x]).copy()
    if winsor:  # robustness: clip extreme CARs (e.g. wildfire-driven crashes)
        lo, hi = d[y].quantile([winsor, 1 - winsor])
        d[y] = d[y].clip(lo, hi)
    # Standardize the signal within each quarter: pure cross-sectional test.
    d["z"] = d.groupby("quarter")[x].transform(lambda s: (s - s.mean()) / s.std(ddof=0))
    d = d.dropna(subset=["z"])
    d["qid"] = d["quarter"].astype(str)
    m = smf.ols(f"{y} ~ z + C(qid)", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(d["qid"])[0]})
    lo, hi = m.conf_int().loc["z"]
    return {"y": y, "signal": x, "n": int(len(d)), "quarters": int(d["qid"].nunique()),
            "coef_bp_per_sd": 1e4 * m.params["z"], "ci95_lo_bp": 1e4 * lo, "ci95_hi_bp": 1e4 * hi,
            "t": m.tvalues["z"], "p": m.pvalues["z"]}


def tercile_spread(ev: pd.DataFrame, y: str, x: str) -> pd.DataFrame:
    d = ev.dropna(subset=[y, x]).copy()
    d["bucket"] = d.groupby("quarter")[x].transform(
        lambda s: pd.qcut(s.rank(method="first"), 3, labels=["Low", "Mid", "High"]))
    return d.groupby("bucket", observed=True)[y].agg(["mean", "count"]).assign(mean=lambda t: t["mean"] * 1e4)
