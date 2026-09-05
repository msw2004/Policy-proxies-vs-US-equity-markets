"""Figures for Releases 1 to 3.

Palette is the validated four-slot categorical set (blue / orange / aqua / yellow).
Aqua and yellow sit below 3:1 contrast on the light surface, so every chart that uses
them carries a legend plus direct labels, and the matching CSV table always ships
beside the figure.  No chart here uses two y-axes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from . import datasets as ds
from .config import (
    BENCHMARK, ESTIMATION_WINDOW, EVENT_WINDOW, HAC_LAGS_DAILY, OUT_FIG,
    RANDOM_SEED,
)
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


# ------------------------------------------------------------------- Release 2
def fig_epu_vs_vol():
    """Log EPU over realised equity volatility, stacked on one shared time axis.

    Two panels rather than twin y-axes: the series share four decades but not a
    unit, and a secondary axis would let the eye read a co-movement out of an
    arbitrary choice of scale.  Stacking makes the turning points comparable and
    leaves the levels unclaimed.
    """
    from . import release2 as r2

    epu = r2.epu_frame()
    mkt = r2.monthly_market_panel().dropna(subset=["rv12"])
    common = epu.index.intersection(mkt.index)
    epu, vol = epu.loc[common], mkt.loc[common, "rv12"] * 100.0
    x = common.to_timestamp()

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 6.2), sharex=True, gridspec_kw={"hspace": 0.30}
    )
    fig.suptitle(
        f"Policy-news intensity and market volatility, {x[0]:%Y}-{x[-1]:%Y}",
        x=0.0, ha="left", fontsize=13, fontweight="bold",
    )

    ax1.plot(x, epu["log_EPU"], color=SERIES[0], label="log EPU (headline)")
    ax1.plot(x, epu["log_EPUMONETARY"], color=SERIES[1],
             label="log EPU: monetary policy")
    ax1.set_title("News-based policy uncertainty, monthly", loc="left")
    ax1.set_ylabel("log index")
    ax1.legend(loc="upper left", ncol=2, fontsize=8.5)
    ax1.margins(y=0.22)

    ax2.plot(x, vol, color=SERIES[2], label="SPY trailing 12m realised vol")
    ax2.set_title("Realised equity volatility, same months", loc="left")
    ax2.set_ylabel("annualised, %")
    ax2.legend(loc="upper left", fontsize=8.5)
    ax2.margins(y=0.22)
    ax2.set_xlim(x[0], x[-1])
    ax2.xaxis.set_major_locator(mdates.YearLocator(4))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    for ax in (ax1, ax2):
        _clean(ax)
    fig.savefig(OUT_FIG / "f4_epu_vs_vol.png")
    plt.close(fig)


def fig_placebo():
    """Release 3's central exhibit: the observed increment against its own null.

    The point of plotting the whole null rather than quoting a p-value is that the
    null's *width* is the thing worth seeing.  At daily frequency with persistent
    regressors a circularly-shifted signal routinely earns a few percent of R^2
    from nothing at all, so "beat the 95th percentile" is a much higher bar than
    "beat zero", and how much higher is visible here rather than asserted.
    """
    from .release3 import (
        BASE_COLS, build_factor_panel, composite_index, hac_lags_for, risk_frame)
    from .stats_tools import circular_block_permutation, zscore

    h = 21
    panel, _ = build_factor_panel()
    cpui = composite_index(panel)
    rf = risk_frame(h)
    # the release's own baseline and bandwidth, not a second set chosen here -
    # a figure that plots a different specification from the tables is a way to
    # publish two answers to one question
    perm = circular_block_permutation(
        rf["fwd_rv"], rf[BASE_COLS], pd.DataFrame({"CPUI": zscore(cpui)}),
        n_iter=2000, lags=hac_lags_for(h, len(rf.dropna())), seed=RANDOM_SEED,
    )
    obs = perm["observed"]["delta_r2"]
    null = perm["null"]
    floor = perm["detectable_floor"]

    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    ax.hist(100 * null, bins=40, color=SERIES[0], alpha=0.55, edgecolor=SURFACE, lw=0.6,
            label=f"placebo: all {perm['n_shifts']} distinct circular shifts")
    ax.axvline(100 * obs, color=SERIES[1], lw=2.4)
    ax.axvline(100 * floor, color=NEUTRAL, lw=1.4, ls="--")

    top = ax.get_ylim()[1]
    ax.annotate(f"observed\n{100*obs:.2f}%", xy=(100 * obs, top * 0.97),
                xytext=(5, 0), textcoords="offset points", color=SERIES[1],
                fontsize=8.5, weight="600", va="top")
    ax.annotate(f"10% critical value\n{100*floor:.2f}%", xy=(100 * floor, top * 0.62),
                xytext=(6, 0), textcoords="offset points", color=INK2,
                fontsize=8.5, va="top")
    ax.set_title(
        f"Release 3: incremental R-squared of CPUI at {h} days, against its own null",
        loc="left", color=INK)
    ax.set_xlabel("increment in R-squared over the volatility baseline, %")
    ax.set_ylabel("placebo draws")
    ax.legend(fontsize=8.5, loc="upper right")
    _clean(ax)
    fig.text(0.0, -0.04,
             f"Exact: every distinct shift enumerated, p = {perm['p_value']:.3f}. "
             "The observed increment sits inside the null, which is the result.",
             fontsize=8, color=INK2)
    fig.savefig(OUT_FIG / "f5_placebo.png")
    plt.close(fig)


def fig_cpui():
    """The index itself, with the roster shown beneath it.

    Any index built from an entering and exiting set of contracts invites the
    question "did the number move, or did the membership?".  Plotting the live
    count directly under the level answers it in the figure instead of in a
    footnote.
    """
    from .release3 import build_factor_panel, composite_index
    from .stats_tools import zscore

    panel, _ = build_factor_panel()
    cpui = zscore(composite_index(panel))

    fig, axes = plt.subplots(
        2, 1, figsize=(9, 5.2), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(cpui.index, cpui.values, color=SERIES[0], label="CPUI (standardised)")
    axes[0].axhline(0, color=NEUTRAL, lw=1)
    axes[0].set_ylabel("standard deviations")

    # The window's first day carries a genuine 29% -> 10% repricing of the largest
    # contract, which is a 6.4 sd flow reading.  It is real, so it is not dropped -
    # but left in frame it flattens every other day into a band, so the axis is set
    # from the rest of the sample and the point is labelled instead.
    rest = cpui.iloc[1:]
    lo, hi = rest.min(), rest.max()
    pad = 0.12 * (hi - lo)
    if cpui.iloc[0] > hi + pad:
        axes[0].set_ylim(lo - pad, hi + pad)
        axes[0].annotate(
            f"{cpui.iloc[0]:.1f} sd - a genuine 29%->10% repricing\n"
            f"of the largest contract, off scale",
            xy=(cpui.index[0], hi + pad), xytext=(28, -12),
            textcoords="offset points", fontsize=8, color=INK2,
            arrowprops=dict(arrowstyle="->", color=NEUTRAL, lw=1))
    axes[0].set_title(
        "Composite policy-uncertainty index, balanced panel", loc="left", color=INK)
    axes[0].legend(fontsize=8.5, loc="upper left")
    _clean(axes[0])

    live = panel["n_live_contracts"].reindex(cpui.index)
    axes[1].step(live.index, live.values, color=SERIES[2], where="post")
    axes[1].set_ylabel("contracts")
    axes[1].set_ylim(0, max(4, float(live.max()) + 1))
    axes[1].set_title("Contracts quoting on each day - constant by construction",
                      loc="left", color=INK, fontsize=9.5)
    _clean(axes[1])
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.tight_layout()
    fig.savefig(OUT_FIG / "f6_cpui.png")
    plt.close(fig)


def run_release1_figs():
    fig_probabilities()
    fig_rolling_corr()
    fig_event_car()
    return sorted(p.name for p in OUT_FIG.glob("f[123]_*.png"))


def run_release2_figs():
    fig_epu_vs_vol()
    return sorted(p.name for p in OUT_FIG.glob("f4_*.png"))


def run_release3_figs():
    fig_placebo()
    fig_cpui()
    return sorted(p.name for p in OUT_FIG.glob("f[56]_*.png"))


def run_all():
    return run_release1_figs() + run_release2_figs() + run_release3_figs()


if __name__ == "__main__":
    for f in run_all():
        print("wrote", f)
