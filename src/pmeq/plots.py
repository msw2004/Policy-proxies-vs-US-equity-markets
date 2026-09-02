"""Release 1 figures.

Palette is the validated four-slot categorical set (blue / orange / aqua / yellow).
Aqua and yellow sit below 3:1 contrast on the light surface, so every chart that uses
them carries a legend plus direct labels, and the matching CSV table always ships
beside the figure.  No chart here uses two y-axes.
"""
from __future__ import annotations

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from . import datasets as ds
from .config import BENCHMARK, ESTIMATION_WINDOW, EVENT_WINDOW, OUT_FIG
from .stats_tools import detect_jumps, event_study

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e3e2de"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
NEUTRAL = "#8a8984"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "grid.color": GRID,
    "axes.grid": True, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "font.size": 9.5, "axes.titlesize": 11, "axes.titleweight": "600",
    "legend.frameon": False, "lines.linewidth": 2.0,
    "figure.dpi": 130, "savefig.bbox": "tight",
})


def _clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def fig_probabilities():
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.6))
    groups = [
        ("Monetary-policy contracts", [
            ("fed_hike_2026", "Fed hike in 2026"),
            ("fed_sep2026_hike25", "Sept-2026: +25bp"),
            ("fed_sep2026_no_change", "Sept-2026: no change"),
        ]),
        ("Other policy contracts", [
            ("us_recession_2026", "US recession by end-2026"),
            ("korea_trade_deal_2027", "US-Korea trade deal"),
            ("gov_shutdown_2025", "US shutdown in 2025"),
            ("us_debt_default_2027", "US debt default by 2027"),
        ]),
    ]
    for ax, (title, items) in zip(axes, groups):
        series = {key: ds.load_polymarket(key) for key, _ in items}
        right_edge = max(v.index[-1] for v in series.values())
        span = right_edge - min(v.index[0] for v in series.values())
        for i, (key, label) in enumerate(items):
            s = series[key]
            ax.plot(s.index, s.values, color=SERIES[i % 4], label=label)
            # direct-label only series that reach the right margin, so a label never
            # lands on top of the legend or another line
            if (right_edge - s.index[-1]) < 0.08 * span:
                ax.annotate(label, xy=(s.index[-1], min(max(s.iloc[-1], 0.03), 0.93)),
                            xytext=(6, 0), textcoords="offset points",
                            color=SERIES[i % 4], fontsize=8.5, va="center", weight="600")
        ax.set_title(title, loc="left", color=INK)
        ax.set_ylabel("implied probability")
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.set_ylim(0, 1.02)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.legend(loc="upper left", fontsize=8, ncols=2)
        _clean(ax)
    fig.suptitle("Polymarket implied probabilities, policy contracts",
                 x=0.02, ha="left", fontsize=12.5, weight="700", color=INK)
    fig.tight_layout(rect=[0, 0, 0.88, 0.96])
    fig.savefig(OUT_FIG / "f1_probabilities.png")
    plt.close(fig)


def fig_rolling_corr(window: int = 21):
    from .release1 import build_pair_frame

    pairs = [("fed_sep2026_hike25", "SPY", "+25bp probability vs SPY"),
             ("fed_sep2026_no_change", "SPY", "no-change probability vs SPY"),
             ("fed_hike_2026", "SPY", "2026 hike probability vs SPY")]
    crit = 1.96 / np.sqrt(window - 3)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for i, (mk, tk, lab) in enumerate(pairs):
        df = build_pair_frame(mk, tk).dropna(subset=["dp"])
        roll = df["dp"].rolling(window).corr(df["ret"])
        ax.plot(roll.index, roll.values, color=SERIES[i], label=lab)
    ax.axhline(0, color=NEUTRAL, lw=1)
    ax.axhspan(-crit, crit, color=GRID, alpha=0.7, zorder=0)
    ax.annotate("not distinguishable from zero", xy=(0.015, 0.5),
                xycoords="axes fraction", color=INK2, fontsize=8, va="center")
    ax.set_title(f"{window}-day rolling correlation: daily change in probability vs SPY return",
                 loc="left", color=INK)
    ax.set_ylabel("correlation")
    ax.set_ylim(-1, 1)
    ax.legend(loc="lower left", fontsize=8.5)
    _clean(ax)
    fig.savefig(OUT_FIG / "f2_rolling_correlation.png")
    plt.close(fig)


def fig_event_car():
    rets = ds.load_returns()
    mkt = rets[BENCHMARK]
    fig, ax = plt.subplots(figsize=(8, 4.4))
    plotted = 0
    for mk, tk in [("fed_hike_2026", "SPY"), ("fed_hike_2026", "VIXY"),
                   ("us_recession_2026", "SPY")]:
        prob = ds.load_polymarket(mk).reindex(rets.index).ffill(limit=3).dropna()
        ev = detect_jumps(prob)
        res = event_study(rets[tk], mkt, ev, EVENT_WINDOW, ESTIMATION_WINDOW,
                          mean_adjusted=(tk == BENCHMARK))
        if res.get("n_events", 0) < 3:
            continue
        car = 100 * res["car"]
        se = 100 * res["car_se"]
        ax.plot(car.index, car.values, color=SERIES[plotted],
                label=f"{mk} -> {tk} (n={res['n_events']})", marker="o", ms=4)
        ax.fill_between(car.index, car - 2 * se, car + 2 * se,
                        color=SERIES[plotted], alpha=0.13, lw=0)
        plotted += 1
    ax.axhline(0, color=NEUTRAL, lw=1)
    ax.axvline(0, color=NEUTRAL, lw=1, ls=":")
    ax.set_title("Cumulative abnormal return around probability jumps (sign-aligned, +/-2 s.e.)",
                 loc="left", color=INK)
    ax.set_xlabel("trading days relative to the jump")
    ax.set_ylabel("CAR, %")
    ax.legend(loc="best", fontsize=8.5)
    _clean(ax)
    fig.savefig(OUT_FIG / "f3_event_car.png")
    plt.close(fig)


def run_all():
    fig_probabilities()
    fig_rolling_corr()
    fig_event_car()
    return sorted(p.name for p in OUT_FIG.glob("*.png"))


if __name__ == "__main__":
    for f in run_all():
        print("wrote", f)
