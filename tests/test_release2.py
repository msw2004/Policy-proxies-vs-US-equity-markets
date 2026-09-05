"""Guardrails for the EPU strand.

The failure modes worth catching here are different from Release 1's.  The EPU
series are monthly, sparse in their early years, and published in two shapes; the
mistakes that would matter are a look-ahead in a "forward" target, a log of zero
silently becoming -inf, a refreshed file written in a shape the loader cannot read,
and the daily strand quietly substituting monthly data when it is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmeq import datasets as ds                                    # noqa: E402
from pmeq import release2                                          # noqa: E402

HAVE_PRICES = (ds.DATA_RAW / "prices" / "SPY_monthly.csv").exists()
needs_prices = pytest.mark.skipif(
    not HAVE_PRICES, reason="run `python -m pmeq.datasets refresh` to fetch SPY bars")


# ------------------------------------------------------------------ the loaders
def test_categorical_epu_parses_to_contiguous_months():
    for s in ("EPUMONETARY", "EPUTRADE", "EPUSOVDEBT"):
        x = ds.load_categorical_epu(s)
        assert isinstance(x.index, pd.PeriodIndex) and x.index.freqstr == "M"
        assert x.index.is_monotonic_increasing and not x.index.has_duplicates
        # no gaps: a monthly index over its own span
        span = pd.period_range(x.index[0], x.index[-1], freq="M")
        assert len(x) == len(span), f"{s} has missing months"
        assert (x >= 0).all() and np.isfinite(x).all()


def test_headline_and_categorical_epu_overlap_the_market_sample():
    epu = ds.load_epu_monthly()
    assert epu.index[0] <= pd.Period("1985-01", freq="M")
    assert epu.index[-1] >= pd.Period("2026-01", freq="M")


# --------------------------------------------------------------- log transform
def test_log_transform_survives_the_exact_zeros_in_the_sparse_subindices():
    """EPUSOVDEBT contains exact zeros in early months.

    `log(x)` would be -inf there and would poison every downstream regression;
    `epu_frame` uses log1p on a clipped series instead.
    """
    sov = ds.load_categorical_epu("EPUSOVDEBT")
    assert (sov == 0).sum() > 0, "fixture assumption: EPUSOVDEBT has exact zeros"

    f = release2.epu_frame()
    logs = [c for c in f.columns if c.startswith("log_")]
    assert logs
    vals = f[logs].to_numpy(dtype=float)
    # NaN at the ragged edge is expected (see the next test); -inf never is
    assert not np.isneginf(vals).any()
    assert np.isfinite(vals[~np.isnan(vals)]).all()


def test_missing_epu_months_sit_only_at_the_ragged_edge():
    """The categorical sub-indices publish a month behind the headline index.

    That is fine - the regressions drop the incomplete tail. An *interior* gap
    would silently shorten every sample instead, so it must not exist.
    """
    f = release2.epu_frame()
    for c in [c for c in f.columns if c.startswith("log_")]:
        s = f[c]
        first, last = s.first_valid_index(), s.last_valid_index()
        assert s.loc[first:last].notna().all(), f"{c} has an interior gap"


# ------------------------------------------------------------------ look-ahead
@needs_prices
def test_forward_monthly_targets_contain_no_look_ahead():
    m = release2.monthly_market_panel()
    # fwd_abs_ret at month t must be |return| of t+1, never of t
    shifted = m["abs_ret"].shift(-1)
    both = pd.concat([m["fwd_abs_ret"], shifted], axis=1).dropna()
    assert np.allclose(both.iloc[:, 0], both.iloc[:, 1])
    assert pd.isna(m["fwd_abs_ret"].iloc[-1])


@needs_prices
def test_forward_rv12_looks_a_full_year_ahead():
    m = release2.monthly_market_panel()
    both = pd.concat([m["fwd_rv12"], m["rv12"].shift(-12)], axis=1).dropna()
    assert len(both) > 100
    assert np.allclose(both.iloc[:, 0], both.iloc[:, 1])
    assert m["fwd_rv12"].tail(12).isna().all()


# ------------------------------------------------------------- the daily strand
def test_daily_strand_reports_unavailability_instead_of_substituting():
    """If the daily snapshot is absent the release must say so, not fall back."""
    out = release2.daily_strand()
    if ds.load_epu_daily() is None:
        assert out["available"] is False
        assert "daily" in out["reason"].lower()
        assert out["table"].empty
    else:
        assert out["available"] is True
        assert len(out["table"]) > 0


def test_load_epu_daily_returns_none_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DATA_RAW", tmp_path)
    assert ds.load_epu_daily() is None


# ----------------------------------------------------------------- the refresh
def test_fred_reshape_matches_what_the_loader_reads(tmp_path, monkeypatch):
    """A refreshed categorical file must be readable by load_categorical_epu.

    `fetch_fred_series` returns a DatetimeIndex named after the series; writing it
    straight out produces a header the loader cannot parse.
    """
    raw = pd.Series([1.0, 2.0, 3.0],
                    index=pd.to_datetime(["1985-01-01", "1985-02-01", "1985-03-01"]),
                    name="EPUTRADE")
    frame = ds.fred_to_month_frame(raw)
    assert list(frame.columns) == ["month", "value"]

    (tmp_path / "epu").mkdir()
    frame.to_csv(tmp_path / "epu" / "EPUTRADE.csv", index=False)
    monkeypatch.setattr(ds, "DATA_RAW", tmp_path)
    back = ds.load_categorical_epu("EPUTRADE")
    assert isinstance(back.index, pd.PeriodIndex)
    assert list(back.values) == [1.0, 2.0, 3.0]
    assert str(back.index[0]) == "1985-01"


# -------------------------------------------------------------------- windowing
@needs_prices
def test_comparison_window_is_release1s_own_estimation_sample():
    """The window must be the price panel, not the union of contract quote dates.

    The union starts eight months earlier because `gov_shutdown_2025` quotes from
    2025-01, a contract Release 1 excludes from its correlation work. Using it
    would compare Release 2 against months Release 1 never sees, and would drop
    the last month it does.
    """
    lo, hi = release2.release1_window()
    px = ds.load_price_panel()
    assert lo == pd.Period(px.index.min(), freq="M")
    assert hi == pd.Period(px.index.max(), freq="M")

    union = ds.load_polymarket_panel()
    assert pd.Period(union.index.min(), freq="M") < lo, (
        "fixture assumption: the contract union really does start earlier")


@needs_prices
def test_short_window_regressions_stay_inside_that_window():
    full = release2.monthly_regressions("full")
    pm = release2.monthly_regressions("polymarket")
    assert len(full) > 0 and len(pm) > 0
    lo, hi = release2.release1_window()
    assert pm["n"].max() <= (hi - lo).n + 1
    assert pm["n"].max() < full["n"].max() / 20
    assert pm["underpowered"].all()


@needs_prices
def test_overlapping_targets_are_refused_when_the_sample_cannot_carry_them():
    """A 12-month overlapping target on 11 months is not an estimate.

    Left ungated it produced t = -11.2 from a HAC estimator whose bandwidth
    equalled its sample size - the loudest number in the release, and an artefact.
    """
    pm = release2.monthly_regressions("polymarket")
    overlapping = {t for t, (_, _, ov) in release2.TARGETS.items() if ov > 1}
    assert overlapping, "fixture assumption: some targets overlap"
    assert not set(pm["target"]) & overlapping, (
        "an overlapping target was estimated on a sample too short to support it")

    full = release2.monthly_regressions("full")
    assert set(full["target"]) & overlapping, "the full sample should carry them"


def test_hac_bandwidth_respects_the_overlap_floor():
    """The plug-in bandwidth is a function of n and cannot see the overlap."""
    from pmeq.stats_tools import nw_lags

    full = release2.monthly_regressions("full") if HAVE_PRICES else None
    if full is None or not len(full):
        pytest.skip("needs prices")
    for _, r in full.iterrows():
        if r["overlap_months"] > 1:
            assert r["hac_lags"] >= r["overlap_months"] - 1
        assert r["hac_lags"] >= nw_lags(r["n"]) or r["overlap_months"] > 1


def test_small_sample_inference_uses_t_not_the_normal():
    """statsmodels defaults robust covariances to use_t=False.

    On n=18 that is the difference between surviving an FDR screen and not, so
    `ols_hac` must set use_t=True on both robust fits.
    """
    from pmeq.stats_tools import ols_hac

    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-31", periods=18, freq="ME")
    x = pd.DataFrame({"x": rng.normal(size=18)}, index=idx)
    y = pd.Series(0.6 * x["x"] + rng.normal(size=18), index=idx)
    m = ols_hac(y, x)
    assert m.model.use_t is True
    assert m.model.df_resid == 16
