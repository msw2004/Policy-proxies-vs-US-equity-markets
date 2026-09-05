"""Guardrails for the long-sample release.

Release 4 is the only release in this study that reports a surviving result, which
makes it the one where a defect would do the most damage. The tests here pin the
published claim, and pin each of the properties that make it credible: that the
target contains no look-ahead, that the surviving cell sits on a target with no
overlap (so it cannot be an artefact of the HAC bandwidth), that the trend control
which overturned Release 3 is present and makes no difference here, and that the
placebo null is enumerated rather than sampled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmeq import datasets as ds                                    # noqa: E402
from pmeq import release4                                          # noqa: E402
from pmeq.stats_tools import (                                     # noqa: E402
    bh_fdr, circular_block_permutation, incremental_r2, nw_lags, zscore,
)

HAVE_PRICES = (ds.DATA_RAW / "prices" / "SPY_monthly.csv").exists()
needs_prices = pytest.mark.skipif(
    not HAVE_PRICES, reason="run `python -m pmeq.datasets refresh` to fetch SPY bars")


# --------------------------------------------------------------------- the data
def test_emv_series_parse_and_span_the_claimed_period():
    for s in release4.EMV_SERIES:
        v = ds.load_emv(s)
        assert isinstance(v.index, pd.PeriodIndex) and v.index.freqstr == "M"
        assert v.index.is_monotonic_increasing and not v.index.has_duplicates
        assert v.index[0] <= pd.Period("1985-01", freq="M")
        assert v.index[-1] >= pd.Period("2026-01", freq="M")
        span = pd.period_range(v.index[0], v.index[-1], freq="M")
        assert len(v) == len(span), f"{s} has missing months"
        assert (v >= 0).all() and np.isfinite(v).all()


@needs_prices
def test_log_transform_is_finite_despite_exact_zeros():
    """The policy components hit exactly zero in sparse months; log(0) would be -inf."""
    raw = pd.DataFrame({s: ds.load_emv(s) for s in release4.EMV_SERIES})
    assert (raw == 0).any().any(), "fixture assumption: some months are exactly zero"
    df = release4.monthly_panel()
    logs = [c for c in df.columns if c.startswith("log_EMV")]
    vals = df[logs].to_numpy(dtype=float)
    assert not np.isneginf(vals).any()


# ---------------------------------------------------------------- look-ahead
@needs_prices
def test_forward_targets_contain_no_look_ahead():
    df = release4.monthly_panel()
    both = pd.concat([df["fwd_abs_ret"], df["abs_ret"].shift(-1)], axis=1).dropna()
    assert len(both) > 300
    assert np.allclose(both.iloc[:, 0], both.iloc[:, 1])
    assert pd.isna(df["fwd_abs_ret"].iloc[-1])

    fwd = pd.concat([df["log_fwd_rv12"], df["log_rv12"].shift(-12)], axis=1).dropna()
    assert len(fwd) > 300
    assert np.allclose(fwd.iloc[:, 0], fwd.iloc[:, 1])
    assert df["log_fwd_rv12"].tail(12).isna().all()


@needs_prices
def test_trailing_volatility_is_not_its_own_control():
    """`log_rv12` as a target must not appear in its own baseline."""
    assert "log_rv12" not in release4.base_cols_for("log_rv12")
    assert "log_rv12" in release4.base_cols_for("fwd_abs_ret")


@needs_prices
def test_the_contemporaneous_target_is_labelled_as_such():
    """Its increments are the largest in the release and are not forecasts."""
    assert release4.TARGETS["log_rv12"][1] == "contemporaneous"
    assert release4.TARGETS["fwd_abs_ret"][1] == "forward"
    assert release4.TARGETS["log_fwd_rv12"][1] == "forward"
    assert "log_rv12" not in release4.FORWARD_TARGETS


# ------------------------------------------------------- the Release 3 controls
@needs_prices
def test_the_trend_control_is_present_in_every_baseline():
    for tgt in release4.TARGETS:
        assert "trend" in release4.base_cols_for(tgt), tgt
    assert "trend" in release4.monthly_panel().columns


@needs_prices
def test_the_trend_makes_no_difference_here_unlike_release3():
    """The control result for what overturned Release 3.

    There the trend carried 85-99% of every increment. Here the EMV series are
    stationary and correlate ~0 with elapsed time over 390 months, so it should
    carry almost nothing - which is the evidence that Release 3's problem was a
    short-window artefact rather than a property of uncertainty measures.
    """
    td = release4.trend_decomposition()
    # every EMV cell on the headline target, including EMV trade - an earlier
    # version filtered out the two rows that would have failed and called the
    # result a pass
    emv = td[td["signal_set"].str.startswith("EMV") &
             (td["target"] == "fwd_abs_ret") &
             td["trend_free_increment_retained"].notna()]
    assert len(emv) >= 2
    retained = emv["trend_free_increment_retained"]
    assert (retained > 0.90).all() and (retained < 1.10).all(), (
        f"an EMV increment moves materially with the trend control: {list(retained)}")

    # and the contrast with Release 3, which is the claim being made
    epu = td[(td["signal_set"] == "EPU headline") & (td["target"] == "fwd_abs_ret")]
    assert bool(epu["increment_grew_with_trend_control"].iloc[0]), (
        "headline EPU should still be flagged as entangled with its own drift")


@needs_prices
def test_hac_bandwidth_floors_at_the_overlap():
    n = 390
    assert release4.hac_lags_for(12, n) >= 11
    assert release4.hac_lags_for(1, n) == nw_lags(n)
    assert release4.hac_lags_for(12, n, 2.0) > release4.hac_lags_for(12, n, 1.0)


@needs_prices
def test_the_surviving_cell_sits_on_a_target_with_no_overlap():
    """Why the headline cannot be a bandwidth artefact.

    Release 2 and Release 3 both had results inflated by a HAC bandwidth blind to
    the target's overlap. The cell that survives here is on a one-month-ahead
    target, whose overlap is 1, so every bandwidth gives the identical t.
    """
    assert release4.TARGETS["fwd_abs_ret"][2] == 1
    lg = release4.lag_sensitivity()
    row = lg[(lg["target"] == "fwd_abs_ret") &
             (lg["signal_set"] == "EMV overall")].iloc[0]
    # absolute lag counts, so this genuinely varies the bandwidth. An earlier
    # version compared `hac_lags_for(1, n, m)` across multipliers, which returns
    # the same number for every m when the overlap is 1 - it asserted a tautology
    # and called it evidence.
    ts = [row[c] for c in ("t_at_1", "t_at_5", "t_at_10", "t_at_20", "t_at_30")
          if c in row and np.isfinite(row[c])]
    assert len(ts) >= 4
    assert max(ts) - min(ts) < 0.4, f"bandwidth moved t by {max(ts)-min(ts):.2f}"
    assert min(ts) > 3.5, "the headline should hold at every bandwidth"


# ------------------------------------------------------------------ the placebo
@needs_prices
def test_the_placebo_null_is_enumerated_not_sampled():
    df = release4.monthly_panel()
    sub = df[["fwd_abs_ret", "log_rv12", "abs_ret", "trend",
              "log_EMVOVERALLEMV"]].dropna()
    out = circular_block_permutation(
        sub["fwd_abs_ret"], sub[["log_rv12", "abs_ret", "trend"]],
        sub[["log_EMVOVERALLEMV"]].apply(zscore),
        n_iter=500, lags=nw_lags(len(sub)), seed=20260901)
    assert out["exact"] is True
    assert out["n_shifts"] == 352
    # not `>= 1/(m+1)`, which (r+1)/(m+1) satisfies unconditionally and so has no
    # power: pin that NO shift beat the observed, which is the actual claim
    assert out["p_value"] == pytest.approx(1.0 / 353, rel=1e-9)
    # and check the gap is real rather than a resolution floor
    assert out["observed"]["delta_r2"] > 5 * out["detectable_floor"]
    assert out["observed"]["delta_r2"] > out["null"].max()


# ------------------------------------------------------------- published claims
@needs_prices
def test_the_headline_claim_reproduces():
    """Pin the one surviving result in the whole study.

    If a change makes this stop surviving, or makes something else start, this
    test is where it should be noticed - not in the README.
    """
    df = release4.monthly_panel()
    cols = ["log_rv12", "abs_ret", "trend"]
    sub = df[["fwd_abs_ret"] + cols + ["log_EMVOVERALLEMV"]].dropna()
    inc = incremental_r2(sub["fwd_abs_ret"], sub[cols],
                         sub[["log_EMVOVERALLEMV"]].apply(zscore),
                         lags=nw_lags(len(sub)))
    assert inc["n"] == 390
    assert inc["delta_r2"] == pytest.approx(0.0596, abs=0.002), (
        f"EMV overall -> next month |return| moved to {inc['delta_r2']:.4f}")
    assert inc["full_model"].tstats["log_EMVOVERALLEMV"] == pytest.approx(4.27, abs=0.15)


@needs_prices
def test_emv_trade_adds_nothing_and_the_reason_is_reported():
    """The most quotable null in the release, and it needs its explanation attached.

    2025 was the largest tariff-news episode on record, so "trade-policy news does
    not help" invites disbelief. The validation table carries the reason: the
    trade component does not track realised volatility at all on this sample.
    """
    val = release4.emv_validation().set_index("series")
    assert abs(val.loc["log_EMVTRADEPOLEMV", "corr_with_log_rv12"]) < 0.10
    assert val.loc["log_EMVOVERALLEMV", "corr_with_log_rv12"] > 0.30


@needs_prices
def test_the_grid_is_fdr_corrected_and_the_verdict_is_stated_both_ways():
    _, placebo = release4.incremental_tests(n_placebo=400)
    for c in ("placebo_p_fdr", "survives_raw_10pct", "survives_fdr_10pct"):
        assert c in placebo.columns
    # pin the published counts, not inequalities BH guarantees anyway
    assert len(placebo) == 18
    assert int(placebo["survives_raw_10pct"].sum()) == 6
    assert int(placebo["survives_fdr_10pct"].sum()) == 5
    fwd = placebo[placebo["target_kind"] == "forward"]
    assert len(fwd) == 12 and int(fwd["survives_fdr_10pct"].sum()) == 4


@needs_prices
def test_the_cross_release_table_admits_only_forward_targets():
    """Release 4's biggest increments are contemporaneous; comparing them with
    Release 3's forward-looking numbers would flatter the news measures."""
    s = release4.cross_release_summary()
    if not len(s):
        pytest.skip("needs r3/r4 placebo tables on disk")
    assert "trailing 12m realised vol (log)" not in set(s["target"])


@needs_prices
def test_power_comparison_uses_release3s_real_sample_size():
    n, n_eff = release4.release3_effective_n()
    assert 100 < n < 200, f"Release 3's n moved to {n}"
    assert n_eff <= n, "effective n cannot exceed the raw n"


# ------------------------------------------------- the two audit-driven verdicts
@needs_prices
def test_the_effect_does_not_survive_the_publication_lag():
    """The finding that decides how Release 4 must be reported.

    EMV for month t is not released until several days into t+1, so a forecast of
    t+1 that uses it is not implementable. At the conservative one-month lag the
    increment falls by about 70% and the out-of-sample gain goes to zero.
    """
    pl = release4.publication_lag(n_placebo=400)
    lag0 = pl[(pl.signal_set == "EMV overall") & (pl.signal_lag_months == 0)].iloc[0]
    lag1 = pl[(pl.signal_set == "EMV overall") & (pl.signal_lag_months == 1)].iloc[0]
    assert not bool(lag0["implementable"]) and bool(lag1["implementable"])
    assert lag1["delta_r2"] < 0.4 * lag0["delta_r2"], (
        "the publication lag no longer bites; recheck before claiming a forecast")


@needs_prices
def test_out_of_sample_gain_vanishes_at_the_implementable_lag():
    oos = release4.out_of_sample()
    a = oos[(oos.signal_set == "EMV overall") & (oos.signal_lag_months == 0)].iloc[0]
    b = oos[(oos.signal_set == "EMV overall") & (oos.signal_lag_months == 1)].iloc[0]
    assert a["oos_r2"] > 0.04, "the lag-0 result should be strong out of sample"
    assert b["oos_r2"] < 0.01, "the implementable version should earn ~nothing"


@needs_prices
def test_the_surviving_cells_are_one_finding_not_four():
    """Four cells clear the FDR grid; given each other, none stands up."""
    rd = release4.redundancy()
    assert len(rd) == 4
    assert rd["t_alone"].abs().max() > 4.0
    assert rd["t_given_others"].abs().max() < 2.0, (
        "a signal now stands up conditional on the others; the README says none does")


@needs_prices
def test_crisis_months_carry_about_half_and_it_is_disclosed():
    c = release4.crisis_robustness().set_index("cut")
    trimmed = c.loc["drop top 5% by target |return|"]
    assert 0.4 < trimmed["share_of_published"] < 0.75
    assert trimmed["t"] > 2.5, "it should survive the trim, just smaller"


@needs_prices
def test_every_signal_target_and_baseline_column_gets_a_stationarity_verdict():
    """The module docstring promises one beside every cell; deliver it."""
    val = release4.emv_validation()
    assert set(val["role"]) == {"signal", "target", "baseline"}
    named = set(val["series"])
    for cols in release4.SIGNAL_SETS.values():
        for c in cols:
            assert c in named, f"{c} has no stationarity verdict"
    assert {"log_rv12", "abs_ret", "fwd_abs_ret", "log_fwd_rv12"} <= named
    assert (val["stationarity"] == "unit root").any(), (
        "fixture assumption: at least one series fails, and it should be visible")
