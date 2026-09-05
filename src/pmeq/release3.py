"""Release 3 - a structured model: from raw probabilities to a policy-uncertainty index.

The weakness of Release 1 is that a raw probability has no stable economic meaning.
A market at 0.90 and a market at 0.10 are both *confident*; a market at 0.50 is
maximally *uncertain*.  Correlating the level with returns therefore mixes two
different objects.  This release fixes that by mapping each contract onto factors
that do have an economic reading, then aggregating them into one index:

  level     logit(p)              - where the crowd sits
  entropy   -p ln p -(1-p)ln(1-p) - how unresolved the question is  (peaks at p=0.5)
  flow      |d logit(p)|          - how much news arrived today
  drift     5-day change in p     - the direction of travel

Aggregation is volume-weighted across contracts, plus a cross-sectional dispersion
term.  The composite CPUI is an equal-weighted average of the standardised
aggregates, so no parameters are fitted on the sample the index is later tested
against.  The dependent variable is the market's *risk level* - realised volatility
over the next h days - rather than its direction.

**The result is null, and the interesting part is why.**

The first version of this release reported that aggregate entropy adds 9% to
R-squared at a five-day horizon with a placebo p of 0.004.  None of that survived
scrutiny:

* ``agg_entropy`` correlates **+0.84 with elapsed time** on the selected window and
  fails an ADF test.  The volatility baseline spans no trend, so the index was
  being paid for reproducing a drift.  Put a linear time index in the baseline and
  85-99% of every increment disappears; the five-day t-statistic falls from 1.79
  to 0.53.  ``trend_decomposition`` is that table.
* The **circular-shift placebo cannot police a trending signal**.  Rotating a
  trend produces a sawtooth with a discontinuity at the wrap, which is a *worse*
  regressor than the original, so the null sits too low and the test over-rejects.
  A deterministic ramp passes it at every horizon.  This is why the trend belongs
  in the baseline rather than being left for the placebo to catch.
* ``p = 0.004`` was **not achievable by the design**.  There are ~145 distinct
  circular shifts on a 160-day panel, so 500 random draws mostly repeat.  The
  placebo now enumerates every distinct shift and reports an exact p-value.
* **No multiplicity correction** was applied to fifteen cells, while Releases 1
  and 2 both correct across their grids.  BH-FDR is applied here now.
* The "volume-weighted aggregate across policy domains" is **82% one contract**
  (``fed_hike_2026``, correlation 0.993 with the aggregate), whose probability
  walks monotonically toward 0.5 across the window - which is where the trend
  comes from.  ``weight_concentration`` is that table.
* The panel rectangle is **chosen from the data** and nothing prices that choice.
  At ``min_days=180`` a different rectangle is selected and the sign of t flips.
  ``rectangle_sensitivity`` is that table.

What remains is a clean negative: on 159 days, with the trend controlled and the
grid corrected, prediction-market factors add nothing to a volatility forecast
that trailing volatility and VIXY do not already provide.  Release 4 puts the same
specification on ~400 months of the Baker-Bloom-Davis-Kost EMV tracker, where
there is enough data for the question to be answerable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import datasets as ds
from .config import (
    BENCHMARK, HAC_LAGS_DAILY, MARKETS, N_PLACEBO, OUT_TAB, RANDOM_SEED,
)
from .stats_tools import (
    bh_fdr, circular_block_permutation, incremental_r2, nw_lags, ols_hac,
    stationarity, zscore,
)

EPS = 0.005
HORIZONS = (5, 10, 21)

# The baseline a policy index has to beat.  `trend` belongs here - see `risk_frame`.
BASE_COLS = ["rv21", "vixy", "abs_ret", "trend"]
BASE_COLS_NO_TREND = ["rv21", "vixy", "abs_ret"]


def hac_lags_for(horizon: int, n: int) -> int:
    """Newey-West bandwidth with a floor set by the target's overlap.

    ``fwd_rv`` at horizon h is built from h days of returns, so consecutive daily
    observations share h-1 of them and the residuals are autocorrelated by
    construction however large the sample is.  The plug-in rule is a function of n
    alone and returns 4 here whatever the horizon, which inflates t by 13-17% at
    the longer ones.  Release 2 hit the identical problem on 12-month overlapping
    targets; this is the same fix.
    """
    return max(nw_lags(n), horizon - 1)


# ------------------------------------------------------------------- factors
def logit(p: pd.Series) -> pd.Series:
    q = p.clip(EPS, 1 - EPS)
    return np.log(q / (1 - q))


def binary_entropy(p: pd.Series) -> pd.Series:
    q = p.clip(EPS, 1 - EPS)
    return -(q * np.log(q) + (1 - q) * np.log(1 - q))


def market_factors(key: str, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Four factors for one contract, aligned to the trading calendar."""
    p = ds.load_polymarket(key).reindex(calendar).ffill(limit=3)
    lg = logit(p)
    return pd.DataFrame({
        "level": lg,
        "entropy": binary_entropy(p),
        "flow": lg.diff().abs(),
        "drift": p.diff(5),
    })


def contract_spans(cal: pd.DatetimeIndex) -> pd.DataFrame:
    """First and last quoting day of every contract on the trading calendar."""
    rows = []
    for m in MARKETS:
        idx = market_factors(m.key, cal)["level"].dropna().index
        if not len(idx):
            continue
        rows.append({"market": m.key, "theme": m.theme, "volume_usd": m.volume_usd,
                     "first": idx.min(), "last": idx.max(), "days": len(idx),
                     "coverage": len(idx) / len(cal)})
    return pd.DataFrame(rows).set_index("market")


def select_balanced_panel(cal: pd.DatetimeIndex, min_days: int = 150) -> tuple[list[str], pd.Timestamp, pd.Timestamp]:
    """Largest contracts-by-days rectangle with no entry or exit inside it.

    An unbalanced panel is the single biggest threat to this index.  Contracts arrive
    and resolve at different dates; the two September-2026 FOMC legs alone carry 77%
    of the volume weight but quote for only the last three and a half months.  Simply
    averaging whatever is live on each day produces an index whose level moves when
    the *roster* changes, which no amount of standardising fully repairs - it just
    converts a step into a trend.  So the primary index is estimated on a rectangle:
    a set of contracts and a window in which every one of them quotes throughout.
    Among rectangles clearing ``min_days``, the one with the most contracts wins, and
    ties break on length.
    """
    from itertools import combinations

    spans = contract_spans(cal)
    keys = list(spans.index)
    for r in range(len(keys), 0, -1):
        best = None
        for combo in combinations(keys, r):
            lo = max(spans.loc[k, "first"] for k in combo)
            hi = min(spans.loc[k, "last"] for k in combo)
            if hi <= lo:
                continue
            days = int(((cal >= lo) & (cal <= hi)).sum())
            if days >= min_days and (best is None or days > best[0]):
                best = (days, list(combo), lo, hi)
        if best is not None:
            return best[1], best[2], best[3]
    raise RuntimeError("no balanced rectangle clears min_days")


def build_factor_panel(
    balanced: bool = True, min_days: int = 150
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Volume-weighted aggregate factors plus a cross-market dispersion term.

    With ``balanced=True`` (the default, and what the reported results use) the panel
    is restricted to the rectangle returned by :func:`select_balanced_panel`, so the
    weights are constant through the window and the index level cannot move because a
    contract arrived or resolved.  ``balanced=False`` keeps every contract and every
    date; it is retained as a robustness check and its entry artefact is quantified in
    :func:`entry_break_diagnostic`.
    """
    rets = ds.load_returns()
    cal = rets.index

    if balanced:
        keys, lo, hi = select_balanced_panel(cal, min_days)
        cal = cal[(cal >= lo) & (cal <= hi)]
    else:
        keys = [m.key for m in MARKETS]

    per_market, weights = {}, {}
    for m in MARKETS:
        if m.key not in keys:
            continue
        f = market_factors(m.key, cal)
        if f["level"].notna().sum() < 60:
            continue
        per_market[m.key] = f
        weights[m.key] = m.volume_usd

    if not per_market:
        raise RuntimeError("no contracts with sufficient overlap")

    w = pd.Series(weights, dtype=float)
    w = w / w.sum()

    agg = {}
    for fac in ("entropy", "flow", "drift", "level"):
        wide = pd.DataFrame({k: v[fac] for k, v in per_market.items()})
        mask = wide.notna()
        ww = mask.mul(w, axis=1)
        ww = ww.div(ww.sum(axis=1).replace(0, np.nan), axis=0)
        agg[f"agg_{fac}"] = (wide * ww).sum(axis=1, min_count=1)
        if fac == "flow":
            agg["disp_flow"] = wide.std(axis=1)
        if fac == "level":
            # cross-sectional dispersion of *changes* in the logit level
            agg["disp_level_chg"] = wide.diff().std(axis=1)

    panel = pd.DataFrame(agg)
    panel["agg_entropy_chg"] = panel["agg_entropy"].diff()
    panel["n_live_contracts"] = pd.DataFrame(
        {k: v["level"].notna() for k, v in per_market.items()}
    ).sum(axis=1)
    panel.attrs["contracts"] = list(per_market)
    panel.attrs["balanced"] = balanced
    panel = panel.dropna(how="all")
    if balanced:
        # quoting outages punch holes in the rectangle; keep only days on which every
        # selected contract actually quotes, so the roster is genuinely constant
        panel = panel[panel["n_live_contracts"] == len(per_market)]
    return panel, pd.DataFrame({k: v["entropy"] for k, v in per_market.items()})


def composite_index(panel: pd.DataFrame, method: str = "equal") -> pd.Series:
    """CPUI - the composite policy-uncertainty index.

    ``method='equal'`` (default) is a plain average of the three standardised
    uncertainty aggregates.  It has no free parameters, so it cannot be accused of
    being fitted to the sample it is then tested on.

    ``method='pca'`` returns the first principal component instead.  PCA loadings are
    estimated on the whole sample, so the index at date t embeds covariance
    information from dates after t; that is fine for describing the sample but not for
    a forecasting claim, and it is labelled in-sample wherever it is reported.
    """
    cols = ["agg_entropy", "agg_flow", "disp_flow"]
    X = panel[cols].dropna()
    if len(X) < 40:
        raise RuntimeError("not enough rows for the composite")

    if method == "equal":
        pc = X.apply(zscore).mean(axis=1)
        pc.name = "CPUI"
        pc.attrs["method"] = "equal-weighted average of standardised components"
        pc.attrs["loadings"] = {c: 1 / len(cols) for c in cols}
        return pc

    from sklearn.decomposition import PCA

    Z = X.apply(zscore)
    pca = PCA(n_components=1)
    pc = pd.Series(pca.fit_transform(Z.values).ravel(), index=Z.index, name="CPUI")
    if np.corrcoef(pc, Z["agg_entropy"])[0, 1] < 0:
        pc = -pc
    pc.attrs["method"] = "first principal component (fitted in-sample)"
    pc.attrs["loadings"] = dict(zip(cols, pca.components_[0]))
    return pc


def roster_diagnostic() -> pd.DataFrame:
    """Show that the balanced panel's roster really is constant, and the other is not.

    2026-05-13 is the day the two highest-volume September-FOMC legs begin quoting.
    On the unbalanced panel the composition of the index changes there, so a level
    shift across that date confounds "policy got more uncertain" with "the roster
    changed".  On the balanced rectangle the roster is identical on every day, so a
    level shift across the same date is information rather than composition - the
    number is reported for both, but it only means the same thing in one of them.
    """
    cut = pd.Timestamp("2026-05-13")
    rows = []
    for balanced, label in ((True, "balanced rectangle (used)"),
                            (False, "all contracts, unbalanced (robustness only)")):
        try:
            panel, _ = build_factor_panel(balanced=balanced)
        except RuntimeError:
            continue
        cpui = composite_index(panel)
        live = panel["n_live_contracts"].reindex(cpui.index)
        before, after = cpui[cpui.index < cut], cpui[cpui.index >= cut]
        rows.append({
            "construction": label,
            "n_contracts": len(panel.attrs["contracts"]),
            "n_days": len(cpui),
            "roster_constant": bool(live.nunique() == 1),
            "contracts_min": int(live.min()), "contracts_max": int(live.max()),
            "mean_before_cut": float(before.mean()) if len(before) else np.nan,
            "mean_after_cut": float(after.mean()) if len(after) else np.nan,
            "shift_in_sd": float((after.mean() - before.mean()) / cpui.std())
            if len(before) and len(after) else np.nan,
        })
    return pd.DataFrame(rows)


def influence_check(horizon: int = 5, signal: str = "agg_entropy") -> pd.DataFrame:
    """Is the surviving result carried by a handful of days?

    159 observations with a persistent regressor is few enough that one repricing
    can do most of the work.  The window's opening day, for instance, carries a
    genuine 29%->10% move in the largest contract and reads 6.4 sd on the flow
    factor.  This drops the most influential days one at a time and re-estimates,
    so a result that depends on any single one of them is visible as such.
    """
    rf = risk_frame(horizon)
    base = rf[BASE_COLS]
    panel, _ = build_factor_panel()
    sig = panel[[signal]].apply(zscore)

    L = hac_lags_for(horizon, len(rf.dropna()))
    full = incremental_r2(rf["fwd_rv"], base, sig, lags=L)
    idx = full["full_model"].resid.index
    # rank days by leverage on the signal: how far the regressor sits from its mean
    z = sig.loc[idx, signal]
    order = z.abs().sort_values(ascending=False).index[:10]

    rows = [{"dropped": "none (full sample)", "n": full["n"],
             "delta_r2": full["delta_r2"],
             "t": full["full_model"].tstats.get(signal, np.nan)}]
    for d in order:
        keep = idx.drop(d)
        try:
            m = incremental_r2(rf["fwd_rv"].loc[keep], base.loc[keep],
                               sig.loc[keep], lags=L)
        except ValueError:
            continue
        rows.append({"dropped": str(d.date()), "n": m["n"],
                     "delta_r2": m["delta_r2"],
                     "t": m["full_model"].tstats.get(signal, np.nan)})
    out = pd.DataFrame(rows)
    out["delta_r2_change"] = out["delta_r2"] - out.loc[0, "delta_r2"]
    return out


def construction_robustness(n_placebo: int = 400) -> pd.DataFrame:
    """Window, contract set, or roster - which one is the result made of?

    The obvious comparison (balanced rectangle vs everything) changes three things
    at once, so a difference between them says nothing about which one matters.
    An earlier version of this release drew exactly that unsupported conclusion,
    reporting a large increment on the rectangle, a near-zero one on the full
    panel, and attributing the gap to the roster.

    With the trend in the baseline the question dissolves: every variant is
    near-zero and none survives its own placebo, so there is no gap left to
    attribute.  The table is kept because that is worth showing - the earlier
    "reproduces on one construction only" story was itself an artefact of the
    missing trend control, not a property of the panel.
    """
    cal = ds.load_returns().index
    keys4, lo, hi = select_balanced_panel(cal)

    def panel_for(balanced, restrict_window):
        panel, _ = build_factor_panel(balanced=balanced)
        if restrict_window:
            panel = panel[(panel.index >= lo) & (panel.index <= hi)]
        return panel

    variants = [
        ("A: rectangle contracts, rectangle window (headline)", True, True),
        ("B: all contracts, full window", False, False),
        ("C: all contracts, rectangle window", False, True),
    ]
    rows = []
    for label, balanced, restrict in variants:
        try:
            panel = panel_for(balanced, restrict)
        except RuntimeError:
            continue
        sig = panel[["agg_entropy"]].apply(zscore)
        for h in HORIZONS:
            rf = risk_frame(h)
            try:
                perm = circular_block_permutation(
                    rf["fwd_rv"], rf[BASE_COLS], sig, n_iter=n_placebo,
                    lags=hac_lags_for(h, len(rf.dropna())), seed=RANDOM_SEED + h,
                )
            except (ValueError, RuntimeError):
                continue
            rows.append({
                "variant": label, "horizon": h,
                "n": perm["observed"]["n"],
                "delta_r2": perm["observed"]["delta_r2"],
                "placebo_p": perm["p_value"],
                "detectable_floor": perm["detectable_floor"],
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ regression
def risk_frame(horizon: int) -> pd.DataFrame:
    """Forecast target and the baseline controls a policy index must beat.

    ``trend`` is a linear time index, and it is not decoration.  Over the selected
    window ``agg_entropy`` correlates +0.84 with elapsed time and fails an ADF
    test; the volatility controls span no trend at all.  A regression of one
    drifting series on another earns R-squared for reproducing a drift, and the
    circular-shift placebo cannot catch it - shifting a trending signal creates a
    sawtooth that is a *worse* regressor than the original, so the null comes out
    too low.  A deterministic ramp passes that placebo at every horizon here.
    Putting the trend in the baseline is what makes the rest of the test mean
    anything, so ``BASE_COLS`` includes it and the trend-free baseline is retained
    only to show how much of the headline it was carrying.
    """
    rets = ds.load_returns()
    spy = rets[BENCHMARK]
    df = pd.DataFrame({
        "fwd_rv": np.log(ds.forward_realized_vol(spy, horizon)),
        "rv21": np.log(ds.realized_vol(spy, 21)),
        "abs_ret": spy.abs(),
        "vixy": np.log(ds.load_price_panel()["VIXY"]),
    })
    df["ret"] = spy
    df["trend"] = np.arange(len(df), dtype=float) / len(df)
    return df


def predictive_tests(n_placebo: int = N_PLACEBO) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    panel, _ = build_factor_panel()
    cpui = composite_index(panel)

    signal_sets = {
        "CPUI": pd.DataFrame({"CPUI": cpui}),
        "agg_entropy": panel[["agg_entropy"]],
        "agg_flow": panel[["agg_flow"]],
        "disp_flow": panel[["disp_flow"]],
        "entropy+flow": panel[["agg_entropy", "agg_flow"]],
    }

    rows, placebo_rows, store = [], [], {}
    for h in HORIZONS:
        rf = risk_frame(h)
        base = rf[BASE_COLS]
        y = rf["fwd_rv"]
        for name, sig in signal_sets.items():
            sig = sig.apply(zscore)
            try:
                inc = incremental_r2(y, base, sig, lags=hac_lags_for(h, len(rf.dropna())))
            except ValueError:
                continue
            m = inc["full_model"]
            for c in sig.columns:
                rows.append({
                    "horizon": h, "signal_set": name, "term": c, "n": inc["n"],
                    "beta": m.params.get(c, np.nan),
                    "t": m.tstats.get(c, np.nan),
                    "p": m.pvalues.get(c, np.nan),
                    "r2_base": inc["r2_base"], "r2_full": inc["r2_full"],
                    "delta_r2": inc["delta_r2"], "delta_adj_r2": inc["delta_adj_r2"],
                    "wald_p": inc["wald_p"],
                })
            store[(h, name)] = inc

            perm = circular_block_permutation(
                y, base, sig, n_iter=n_placebo,
                lags=hac_lags_for(h, len(rf.dropna())), seed=RANDOM_SEED + h
            )
            placebo_rows.append({
                "horizon": h, "signal_set": name, "n": inc["n"],
                "delta_r2": inc["delta_r2"],
                "placebo_mean_delta_r2": perm["null_mean"],
                # smallest increment this placebo could ever call significant: when
                # this floor is large the test has no power, and "does not survive"
                # is uninformative rather than evidence of absence
                "detectable_floor": perm["detectable_floor"],
                "placebo_q95_delta_r2": perm["null_q95"],
                "placebo_p": perm["p_value"],
                "n_shifts": perm["n_shifts"],
                "exact_null": perm["exact"],
            })
    placebo = pd.DataFrame(placebo_rows)
    if len(placebo):
        # Fifteen cells are computed here and Releases 1 and 2 both correct across
        # their grids; not correcting across this one would be special pleading.
        # The five signal sets overlap (CPUI and entropy+flow both contain
        # agg_entropy), and positive dependence is the case BH is valid - and
        # conservative - under, so the correction is if anything too gentle.
        placebo["placebo_p_fdr"] = bh_fdr(placebo["placebo_p"])
        placebo["survives_raw_10pct"] = placebo["placebo_p"] < 0.10
        placebo["survives_fdr_10pct"] = placebo["placebo_p_fdr"] < 0.10
    return pd.DataFrame(rows), placebo, store


def trend_decomposition() -> pd.DataFrame:
    """How much of each increment is a shared drift rather than a relationship?

    This is the single most important table in the release.  ``agg_entropy``
    correlates +0.84 with elapsed time over the selected window and does not pass
    an ADF test; the volatility controls span no trend.  Estimating with and
    without a linear time index in the baseline separates "this index says
    something about future volatility" from "both series drifted upward over eight
    months", and on this sample it is almost entirely the latter.
    """
    panel, _ = build_factor_panel()
    cpui = composite_index(panel)
    sets = {"CPUI": pd.DataFrame({"CPUI": cpui}),
            "agg_entropy": panel[["agg_entropy"]],
            "agg_flow": panel[["agg_flow"]],
            "disp_flow": panel[["disp_flow"]]}

    rows = []
    for h in HORIZONS:
        rf = risk_frame(h)
        L = hac_lags_for(h, len(rf.dropna()))
        for name, sig in sets.items():
            z = sig.apply(zscore)
            try:
                no_t = incremental_r2(rf["fwd_rv"], rf[BASE_COLS_NO_TREND], z, lags=L)
                with_t = incremental_r2(rf["fwd_rv"], rf[BASE_COLS], z, lags=L)
            except ValueError:
                continue
            col = sig.columns[0]
            d0, d1 = no_t["delta_r2"], with_t["delta_r2"]
            rows.append({
                "horizon": h, "signal": name, "n": with_t["n"],
                "delta_r2_no_trend": d0, "delta_r2_with_trend": d1,
                "share_explained_by_trend": 1 - d1 / d0 if d0 > 0 else np.nan,
                "t_no_trend": no_t["full_model"].tstats.get(col, np.nan),
                "t_with_trend": with_t["full_model"].tstats.get(col, np.nan),
            })
    return pd.DataFrame(rows)


def rectangle_sensitivity() -> pd.DataFrame:
    """Does the answer depend on the constant that selects the panel?

    ``select_balanced_panel`` chooses both the contracts and the window from the
    data, and nothing downstream prices that choice - the placebo rotates the
    signal inside an already-chosen rectangle.  So the least the release can do is
    show what other rectangles would have said.
    """
    rows = []
    for md in (100, 120, 150, 180):
        try:
            panel, _ = build_factor_panel(min_days=md)
        except RuntimeError:
            continue
        sig = panel[["agg_entropy"]].apply(zscore)
        for h in HORIZONS:
            rf = risk_frame(h)
            L = hac_lags_for(h, len(rf.dropna()))
            try:
                inc = incremental_r2(rf["fwd_rv"], rf[BASE_COLS], sig, lags=L)
            except ValueError:
                continue
            rows.append({
                "min_days": md,
                "contracts": len(panel.attrs["contracts"]),
                "window": f"{panel.index[0].date()}..{panel.index[-1].date()}",
                "horizon": h, "n": inc["n"],
                "delta_r2": inc["delta_r2"],
                "t": inc["full_model"].tstats.get("agg_entropy", np.nan),
            })
    return pd.DataFrame(rows)


def weight_concentration() -> pd.DataFrame:
    """What the "volume-weighted aggregate across policy domains" actually is."""
    panel, _ = build_factor_panel()
    keys = panel.attrs["contracts"]
    vol = pd.Series({m.key: m.volume_usd for m in MARKETS if m.key in keys})
    w = vol / vol.sum()
    cal = panel.index
    rows = []
    for k in keys:
        ent = market_factors(k, cal)["entropy"]
        rows.append({
            "market": k, "volume_usd": float(vol[k]), "weight": float(w[k]),
            "corr_with_aggregate": float(ent.corr(panel["agg_entropy"])),
        })
    return pd.DataFrame(rows).sort_values("weight", ascending=False)


def contemporaneous_risk_table() -> pd.DataFrame:
    """Does CPUI describe *today's* risk level?

    Reported in levels **and** in first differences, because on this window the two
    disagree about the sign and only one of them is trustworthy.  Both CPUI and
    log VIXY fail an ADF test here, and VIXY - a short-dated VIX-futures ETF -
    loses 43 log-percent to roll decay over eight months, so a levels regression
    of one on the other is two drifts meeting.  It returns a *negative*
    coefficient: more policy uncertainty, less implied volatility.  In differences
    the sign flips to positive and stays significant, which is both the
    economically sensible direction and the only one of the two that a stationary
    regression supports.  The levels row is kept so the trap is visible.
    """
    panel, _ = build_factor_panel()
    cpui = zscore(composite_index(panel))
    rets = ds.load_returns()
    spy = rets[BENCHMARK]

    targets = [
        ("log realised vol (21d, trailing)", np.log(ds.realized_vol(spy, 21))),
        ("log VIXY level", np.log(ds.load_price_panel()["VIXY"])),
        ("|SPY return|", spy.abs()),
    ]
    rows = []
    for lbl, y in targets:
        for spec in ("levels", "changes"):
            yy, xx = (y, cpui) if spec == "levels" else (y.diff(), cpui.diff())
            df = pd.DataFrame({"y": yy, "CPUI": xx}).dropna()
            if len(df) < 40:
                continue
            m = ols_hac(df["y"], df[["CPUI"]], lags=HAC_LAGS_DAILY)
            st = stationarity(df["y"])
            rows.append({
                "target": lbl, "spec": spec, "n": m.nobs,
                "beta_CPUI": m.params.get("CPUI", np.nan),
                "t": m.tstats.get("CPUI", np.nan),
                "p": m.pvalues.get("CPUI", np.nan),
                "r2": m.r2,
                "target_stationarity": st["verdict"],
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- run
def run(n_placebo: int = N_PLACEBO) -> dict:
    panel, entropies = build_factor_panel()
    cpui = composite_index(panel)
    pred, placebo, store = predictive_tests(n_placebo)
    contemp = contemporaneous_risk_table()

    panel.assign(CPUI=cpui).to_csv(OUT_TAB / "r3_factor_panel.csv")
    pred.to_csv(OUT_TAB / "r3_predictive.csv", index=False)
    placebo.to_csv(OUT_TAB / "r3_placebo.csv", index=False)
    contemp.to_csv(OUT_TAB / "r3_contemporaneous.csv", index=False)

    loadings = pd.Series(cpui.attrs["loadings"], name="loading").to_frame()
    loadings["method"] = cpui.attrs["method"]
    loadings.to_csv(OUT_TAB / "r3_cpui_loadings.csv")

    roster = roster_diagnostic()
    roster.to_csv(OUT_TAB / "r3_roster.csv", index=False)
    influence = influence_check()
    influence.to_csv(OUT_TAB / "r3_influence.csv", index=False)
    trend = trend_decomposition()
    trend.to_csv(OUT_TAB / "r3_trend_decomposition.csv", index=False)
    rect = rectangle_sensitivity()
    rect.to_csv(OUT_TAB / "r3_rectangle_sensitivity.csv", index=False)
    weights = weight_concentration()
    weights.to_csv(OUT_TAB / "r3_weight_concentration.csv", index=False)
    robust = construction_robustness(n_placebo=min(400, max(100, n_placebo // 4)))
    robust.to_csv(OUT_TAB / "r3_construction_robustness.csv", index=False)

    return {"panel": panel, "cpui": cpui, "entropies": entropies,
            "predictive": pred, "placebo": placebo, "contemporaneous": contemp,
            "store": store, "loadings": loadings, "roster": roster,
            "robustness": robust, "influence": influence, "trend": trend,
            "rectangle": rect, "weights": weights}


if __name__ == "__main__":
    out = run(n_placebo=500)
    print("CPUI construction:", out["cpui"].attrs["method"])
    print()
    print("=== panel composition ===")
    print(out["roster"].round(4).to_string(index=False))
    print()
    print("=== does the headline factor survive the other construction? ===")
    print(out["robustness"].round(4).to_string(index=False))
    print()
    print("=== incremental predictive power over (trailing RV, VIXY, |ret|) ===")
    print(out["predictive"].round(4).to_string(index=False))
    print()
    print("=== circular-shift placebo ===")
    print(out["placebo"].round(4).to_string(index=False))
    print()
    print("=== contemporaneous risk description ===")
    print(out["contemporaneous"].round(4).to_string(index=False))
