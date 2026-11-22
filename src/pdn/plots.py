"""Static README figures (matplotlib). Palette: validated categorical order."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .config import BA_NAME, FIGURES  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
POS, NEG = "#2a78d6", "#eb6834"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _fig(w=9, h=4.8):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    return fig, ax


def _ts(levels: pd.DataFrame) -> pd.DataFrame:
    d = levels.copy()
    d["t"] = d["month"].dt.to_timestamp()
    return d


def growth_lines(levels: pd.DataFrame, bas: list, fname: str, title: str, roll: int = 3):
    d = _ts(levels)
    fig, ax = _fig()
    for i, ba in enumerate(bas):
        s = d[d["ba"] == ba].set_index("t")["wn_yoy"].rolling(roll, min_periods=roll).mean() * 100
        ax.plot(s.index, s.values, color=SERIES[i], lw=2, label=BA_NAME[ba])
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("Weather-normalized YoY growth (%)", color=INK2, fontsize=9)
    ax.set_title(title, loc="left", color=INK, fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, ncol=min(len(bas), 4), loc="upper left")
    fig.text(0.01, 0.01, f"{roll}-month average. Source: EIA-930, Open-Meteo; model in src/pdn/model.py",
             fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / fname, facecolor=SURFACE)
    plt.close(fig)


def raw_vs_normalized(levels: pd.DataFrame, ba: str, fname: str):
    d = _ts(levels[levels["ba"] == ba]).set_index("t")
    fig, ax = _fig()
    ax.plot(d.index, d["raw_yoy"] * 100, color=SERIES[1], lw=1.5, label="Raw YoY (includes weather)")
    ax.plot(d.index, d["wn_yoy"] * 100, color=SERIES[0], lw=2, label="Weather-normalized YoY")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("YoY change in avg daily demand (%)", color=INK2, fontsize=9)
    ax.set_title(f"{BA_NAME[ba]}: removing weather reveals the underlying trend", loc="left",
                 color=INK, fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIGURES / fname, facecolor=SURFACE)
    plt.close(fig)


def latest_bar(levels: pd.DataFrame, fname: str, months: int = 12):
    d = levels.dropna(subset=["wn_yoy"])
    last = d["month"].max()
    win = d[d["month"] > last - months]
    g = win.groupby("ba")["wn_yoy"].mean().sort_values() * 100
    fig, ax = _fig(8, 6.5)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    colors = [POS if v >= 0 else NEG for v in g.values]
    ax.barh([BA_NAME[b] for b in g.index], g.values, color=colors, height=0.7)
    for y, v in enumerate(g.values):
        # Negative labels sit right of the zero line so they never hit the axis labels.
        ax.text(max(v, 0) + 0.15, y, f"{v:+.1f}%", va="center", ha="left", fontsize=8, color=INK2)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlabel("Average weather-normalized YoY growth (%)", color=INK2, fontsize=9)
    ax.set_title(f"Underlying demand growth, {months} months to {last.strftime('%b %Y')}",
                 loc="left", color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES / fname, facecolor=SURFACE)
    plt.close(fig)
    return g


def coef_chart(res: pd.DataFrame, fname: str):
    """Point estimate and 95% CI per (window, signal): CAR in bp per 1 SD of signal."""
    win = {"car_pre": "Pre-earnings\n(signal date to day -2)",
           "car_ann": "Announcement\n(days -1 to +1)",
           "car_post": "Post-earnings\n(days +2 to +40)"}
    sig = {"accel": ("Growth acceleration", SERIES[0]),
           "growth": ("Weather-normalized growth", SERIES[1]),
           "raw": ("Raw growth (with weather)", SERIES[2])}
    fig, ax = _fig(9, 4.6)
    ys = list(win)
    for j, (k, (lab, col)) in enumerate(sig.items()):
        d = res[res["signal"] == k].set_index("y").reindex(ys)
        y = [i + (j - 1) * 0.22 for i in range(len(ys))]
        ax.errorbar(d["coef_bp_per_sd"], y,
                    xerr=[d["coef_bp_per_sd"] - d["ci95_lo_bp"], d["ci95_hi_bp"] - d["coef_bp_per_sd"]],
                    fmt="o", color=col, ms=6, capsize=3, lw=1.5, label=lab)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(range(len(ys)))
    ax.set_yticklabels([win[k] for k in ys], fontsize=9, color=INK2)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_xlabel("Abnormal return per 1 SD of signal (bp), 95% CI", color=INK2, fontsize=9)
    ax.set_title("Grid-demand signals vs utility stock returns around earnings", loc="left",
                 color=INK, fontsize=12)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=3, borderaxespad=0.2)
    ax.set_title("Grid-demand signals vs utility stock returns around earnings", loc="left",
                 color=INK, fontsize=12, pad=26)
    fig.text(0.01, 0.01, "28 utilities, 2022Q1 to 2026Q3, returns vs XLU, quarter fixed effects, "
             "SEs clustered by quarter", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIGURES / fname, facecolor=SURFACE)
    plt.close(fig)
