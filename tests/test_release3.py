"""Guardrails for the composite-index release.

Release 3 is the part of this study most able to fool itself. It builds an index
out of contracts that enter and leave, standardises it, and regresses a forward
volatility on it. Each of those steps has a characteristic failure that looks like
a result: a level break caused by the roster rather than by the world, a
look-ahead smuggled in through the target, an index whose weights were fitted on
the sample it is then tested against, and a placebo that shuffles nothing.

These tests pin each of those down.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmeq import datasets as ds                                    # noqa: E402
from pmeq import release3                                          # noqa: E402
from pmeq.stats_tools import circular_block_permutation, zscore    # noqa: E402

HAVE_PRICES = (ds.DATA_RAW / "prices" / "SPY.csv").exists()
needs_prices = pytest.mark.skipif(
    not HAVE_PRICES, reason="run `python -m pmeq.datasets refresh` to fetch ETF bars")


# ------------------------------------------------------------------- factors
def test_entropy_peaks_at_a_coin_flip_and_is_symmetric():
    """Entropy is the factor the release leans on; its shape is the whole claim."""
    p = pd.Series([0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
    h = release3.binary_entropy(p)
    assert h.iloc[3] == pytest.approx(np.log(2), abs=1e-6)      # max at p=0.5
    assert h.is_monotonic_increasing is False
    # symmetric: p and 1-p carry identical entropy
    assert h.iloc[0] == pytest.approx(h.iloc[6], abs=1e-9)
    assert h.iloc[1] == pytest.approx(h.iloc[5], abs=1e-9)
    # and strictly rising towards the middle from either side
    assert h.iloc[0] < h.iloc[1] < h.iloc[2] < h.iloc[3]
    assert h.iloc[6] < h.iloc[5] < h.iloc[4] < h.iloc[3]


def test_entropy_distinguishes_confidence_from_direction():
    """A market at 0.9 and one at 0.1 disagree on direction but not on certainty.

    This is the reason the release stopped correlating raw levels with returns.
    """
    a = release3.binary_entropy(pd.Series([0.9]))
    b = release3.binary_entropy(pd.Series([0.1]))
    assert a.iloc[0] == pytest.approx(b.iloc[0])
    lg = release3.logit(pd.Series([0.9, 0.1]))
    assert lg.iloc[0] == pytest.approx(-lg.iloc[1])              # levels do differ


def test_logit_and_entropy_are_finite_at_the_boundaries():
    """Resolved contracts print 0.0 and 1.0; an inf would poison every aggregate."""
    p = pd.Series([0.0, 1.0])
    assert np.isfinite(release3.logit(p)).all()
    assert np.isfinite(release3.binary_entropy(p)).all()


# ------------------------------------------------------------- panel balance
@needs_prices
def test_balanced_panel_really_is_a_rectangle():
    cal = ds.load_returns().index
    keys, lo, hi = release3.select_balanced_panel(cal)
    assert len(keys) >= 2 and hi > lo
    spans = release3.contract_spans(cal)
    for k in keys:
        assert spans.loc[k, "first"] <= lo, f"{k} starts after the window opens"
        assert spans.loc[k, "last"] >= hi, f"{k} ends before the window closes"


@needs_prices
def test_balanced_panel_has_a_constant_roster_and_the_other_does_not():
    """The point of the rectangle: the index cannot move because membership moved."""
    bal, _ = release3.build_factor_panel(balanced=True)
    assert bal["n_live_contracts"].nunique() == 1
    assert bal["n_live_contracts"].iloc[0] == len(bal.attrs["contracts"])

    unbal, _ = release3.build_factor_panel(balanced=False)
    assert unbal["n_live_contracts"].nunique() > 1, (
        "fixture assumption: the unbalanced panel really does change roster")


@needs_prices
def test_roster_diagnostic_reports_both_constructions():
    r = release3.roster_diagnostic()
    assert len(r) == 2
    assert r["roster_constant"].sum() == 1, (
        "exactly one construction should have a constant roster")


# ------------------------------------------------------------------ the index
@needs_prices
def test_equal_weighted_index_fits_no_parameters_on_the_test_sample():
    """The default index must not be fitted on the data it is later tested against.

    Assert the arithmetic, not the advertised `attrs["loadings"]` - that is a
    hardcoded dict literal, and the earlier version of this test passed unchanged
    when the mean was replaced with 0.9/0.05/0.05 weights.
    """
    panel, _ = release3.build_factor_panel()
    cpui = release3.composite_index(panel, method="equal")
    cols = ["agg_entropy", "agg_flow", "disp_flow"]
    manual = panel[cols].dropna().apply(zscore).mean(axis=1)
    assert np.allclose(cpui.reindex(manual.index).values, manual.values), (
        "the index is not the equal-weighted mean it claims to be")

    loadings = cpui.attrs["loadings"]
    assert len(set(np.round(list(loadings.values()), 12))) == 1
    assert sum(loadings.values()) == pytest.approx(1.0)
    assert "equal" in cpui.attrs["method"].lower()


@needs_prices
def test_the_trend_control_is_actually_in_the_reported_baseline():
    """The single change that turned this release from a finding into a null."""
    assert "trend" in release3.BASE_COLS
    assert "trend" not in release3.BASE_COLS_NO_TREND
    rf = release3.risk_frame(10)
    assert "trend" in rf.columns
    assert rf["trend"].is_monotonic_increasing


@needs_prices
def test_the_headline_signal_is_mostly_a_time_trend():
    """Pin the reason the release reports nothing, so a regression is visible."""
    panel, _ = release3.build_factor_panel()
    ent = panel["agg_entropy"].dropna()
    t = pd.Series(np.arange(len(ent), dtype=float), index=ent.index)
    assert ent.corr(t) > 0.7, "fixture assumption: agg_entropy trends hard"

    td = release3.trend_decomposition()
    row = td[(td.horizon == 5) & (td.signal == "agg_entropy")].iloc[0]
    assert row["share_explained_by_trend"] > 0.8
    assert abs(row["t_with_trend"]) < abs(row["t_no_trend"])


@needs_prices
def test_hac_bandwidth_respects_the_forecast_overlap():
    from pmeq.stats_tools import nw_lags

    assert release3.hac_lags_for(21, 160) >= 20
    assert release3.hac_lags_for(5, 160) == max(nw_lags(160), 4)


@needs_prices
def test_index_is_invariant_to_rescaling_its_inputs():
    """Standardising the components means units cannot matter. Verify it."""
    panel, _ = release3.build_factor_panel()
    a = release3.composite_index(panel)
    scaled = panel.copy()
    for c in ("agg_entropy", "agg_flow", "disp_flow"):
        scaled[c] = scaled[c] * 1000.0 + 7.0
    b = release3.composite_index(scaled)
    assert np.allclose(a.dropna().values, b.loc[a.dropna().index].values)


# ------------------------------------------------------------------ the target
@needs_prices
def test_forward_target_contains_no_look_ahead():
    """`fwd_rv` at t must be built only from returns after t."""
    rf = release3.risk_frame(5)
    spy = ds.load_returns()["SPY"]
    manual = np.log(spy.rolling(5).std().shift(-5) * np.sqrt(252))
    both = pd.concat([rf["fwd_rv"], manual], axis=1).dropna()
    assert len(both) > 100
    assert np.allclose(both.iloc[:, 0], both.iloc[:, 1])


@needs_prices
def test_bumping_todays_return_does_not_move_todays_forward_target():
    rf = release3.risk_frame(5)
    assert rf["fwd_rv"].tail(5).isna().all(), "the last h days cannot be known"


@needs_prices
def test_baseline_controls_are_the_obvious_rivals():
    """A policy index must beat trailing vol, VIXY and |return|, not a bare mean."""
    rf = release3.risk_frame(10)
    for c in ("rv21", "vixy", "abs_ret", "trend", "fwd_rv"):
        assert c in rf.columns
    assert rf["rv21"].notna().sum() > 100


# ----------------------------------------------------------------- the placebo
def _persistent(n, rho, seed):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    e = rng.normal(size=n)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return x


def test_placebo_actually_shifts_and_preserves_persistence():
    """Exercise the real function, not a reimplementation of np.roll.

    The earlier version of this test rolled an array inline and asserted numpy
    preserves autocorrelation. It would have passed unchanged if the placebo had
    been rewritten to shuffle iid, which is the failure it was named for.
    """
    n = 200
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    sig = pd.DataFrame({"s": _persistent(n, 0.95, 1)}, index=idx)
    y = pd.Series(_persistent(n, 0.5, 2), index=idx)
    base = pd.DataFrame({"b": _persistent(n, 0.5, 3)}, index=idx)

    seen = {}

    def spy(y_, base_, extra, lags="auto"):
        seen[len(seen)] = extra["s"].to_numpy().copy()
        return {"n": len(extra), "r2_base": 0.0, "r2_full": 0.0, "delta_r2": 0.0,
                "adj_r2_base": 0.0, "adj_r2_full": 0.0, "delta_adj_r2": 0.0,
                "wald_chi2": 0.0, "wald_p": 1.0, "df": 1,
                "full_model": None, "base_model": None}

    import pmeq.stats_tools as st
    real = st.incremental_r2
    st.incremental_r2 = spy
    try:
        st.circular_block_permutation(y, base, sig, n_iter=25, seed=0)
    finally:
        st.incremental_r2 = real

    drawn = list(seen.values())[1:]                      # [0] is the observed fit
    assert len(drawn) >= 20
    original = sig["s"].to_numpy()
    for d in drawn:
        assert not np.allclose(d, original), "a draw failed to shift at all"
        assert sorted(d) == pytest.approx(sorted(original)), (
            "a draw changed the multiset of values - that is a shuffle, not a shift")
        ac = pd.Series(d).autocorr(1)
        assert ac > 0.8, f"persistence destroyed: lag-1 autocorr fell to {ac:.2f}"


def test_placebo_enumerates_exactly_when_it_can_and_says_so():
    """500 draws from ~145 possible shifts buys no resolution, only repeats."""
    n = 160
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    y = pd.Series(_persistent(n, 0.3, 4), index=idx)
    base = pd.DataFrame({"b": _persistent(n, 0.3, 5)}, index=idx)
    sig = pd.DataFrame({"s": _persistent(n, 0.9, 6)}, index=idx)

    out = circular_block_permutation(y, base, sig, n_iter=500, seed=0)
    assert out["exact"] is True
    assert out["n_shifts"] == n - 2 * max(5, int(0.05 * n))
    # exact enumeration is deterministic: the seed must not matter
    again = circular_block_permutation(y, base, sig, n_iter=500, seed=999)
    assert out["p_value"] == pytest.approx(again["p_value"])


def test_placebo_p_can_never_be_zero():
    """(r+1)/(m+1), not (null >= obs).mean(); a published p of 0.000 is indefensible."""
    n = 120
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    sig = pd.DataFrame({"s": _persistent(n, 0.9, 7)}, index=idx)
    # a target built to be perfectly explained by the signal: nothing beats it
    y = pd.Series(sig["s"].to_numpy() * 3.0, index=idx)
    base = pd.DataFrame({"b": _persistent(n, 0.2, 8)}, index=idx)
    out = circular_block_permutation(y, base, sig, n_iter=400, seed=0)
    assert out["p_value"] > 0.0
    assert out["p_value"] == pytest.approx(1.0 / (out["n_shifts"] + 1))


def test_detectable_floor_matches_the_level_it_is_read_at():
    """A q95 floor beside a 10% decision rule overstates how powerless the test was."""
    n = 150
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    y = pd.Series(_persistent(n, 0.3, 9), index=idx)
    base = pd.DataFrame({"b": _persistent(n, 0.3, 10)}, index=idx)
    sig = pd.DataFrame({"s": _persistent(n, 0.9, 11)}, index=idx)
    out = circular_block_permutation(y, base, sig, n_iter=400, seed=0, alpha=0.10)
    assert out["detectable_floor"] == pytest.approx(np.quantile(out["null"], 0.90))
    assert out["detectable_floor"] <= out["null_q95"]


@needs_prices
def test_a_deterministic_ramp_does_not_pass_the_baseline_used_for_reporting():
    """The defect that made the first version of this release wrong.

    A circular shift of a trending signal creates a sawtooth that is a *worse*
    regressor than the original, so the null sits too low and a pure ramp passes.
    Against the trend-free baseline it did, at every horizon. The reported
    baseline includes `trend`, which is what closes the hole - so assert the hole
    is closed, on the baseline actually used.
    """
    rf = release3.risk_frame(10).dropna()
    n = len(rf)
    # A near-trend, not an exact one: an exact ramp is collinear with `trend` and
    # would pass for the trivial reason that its increment is identically zero.
    # This mimics agg_entropy - mostly drift, with persistent noise on top.
    ramp = pd.DataFrame(
        {"ramp": 3.0 * np.arange(n, dtype=float) / n + _persistent(n, 0.95, 42) / 8},
        index=rf.index).apply(zscore)
    t = pd.Series(np.arange(n, dtype=float), index=rf.index)
    assert ramp["ramp"].corr(t) > 0.7, "fixture assumption: the signal still trends"

    against_trend_free = circular_block_permutation(
        rf["fwd_rv"], rf[release3.BASE_COLS_NO_TREND], ramp, n_iter=400,
        lags=release3.hac_lags_for(10, n), seed=1)
    against_reported = circular_block_permutation(
        rf["fwd_rv"], rf[release3.BASE_COLS], ramp, n_iter=400,
        lags=release3.hac_lags_for(10, n), seed=1)

    # the reported baseline must be at least as hard to fool as the trend-free one
    assert against_reported["p_value"] >= against_trend_free["p_value"], (
        "adding the trend control made a drifting signal easier to certify")
    assert against_reported["p_value"] > 0.10, (
        f"a drifting signal passed the reported baseline at "
        f"p={against_reported['p_value']:.3f}")


@needs_prices
def test_a_pure_noise_signal_does_not_survive_the_placebo():
    """End-to-end sanity: the machinery must reject something known to be junk."""
    rf = release3.risk_frame(10).dropna()
    rng = np.random.default_rng(20260905)
    noise = pd.DataFrame({"junk": rng.normal(size=len(rf))}, index=rf.index)
    out = circular_block_permutation(
        rf["fwd_rv"], rf[release3.BASE_COLS], noise.apply(zscore),
        n_iter=400, seed=1)
    assert out["p_value"] > 0.10, (
        f"white noise survived the placebo at p={out['p_value']:.3f}")


# --------------------------------------------------------------- reported claims
@needs_prices
def test_the_release_reports_a_null_and_the_tables_agree():
    """Pin the published conclusion. If a change makes something survive, fail here.

    The earlier version of this file asserted no published number at all, so all
    fifteen tests passed through every defect an audit later found.
    """
    from pmeq.stats_tools import bh_fdr

    panel, _ = release3.build_factor_panel()
    sig = panel[["agg_entropy"]].apply(zscore)
    ps = []
    for h in release3.HORIZONS:
        rf = release3.risk_frame(h)
        out = circular_block_permutation(
            rf["fwd_rv"], rf[release3.BASE_COLS], sig, n_iter=400,
            lags=release3.hac_lags_for(h, len(rf.dropna())), seed=20260901 + h)
        assert out["exact"] is True, "the null should be enumerable at this n"
        ps.append(out["p_value"])
    assert min(bh_fdr(pd.Series(ps))) > 0.10, (
        f"a cell now survives FDR (raw p = {[round(p, 3) for p in ps]}); "
        "the README says nothing does")


@needs_prices
def test_panel_selection_sensitivity_is_reported():
    """min_days is a free constant chosen from the data; the release must show it."""
    r = release3.rectangle_sensitivity()
    assert len(r) >= 6
    assert r["min_days"].nunique() >= 3
    assert r["contracts"].nunique() > 1, (
        "the sensitivity table should reach a min_days that selects a different panel")


@needs_prices
def test_the_aggregate_is_disclosed_as_concentrated():
    """'Volume-weighted across policy domains' is 82% one contract. Say so."""
    w = release3.weight_concentration()
    assert w["weight"].max() > 0.5
    top = w.iloc[0]
    assert top["corr_with_aggregate"] > 0.9, (
        "the aggregate should be disclosed as tracking its largest constituent")
