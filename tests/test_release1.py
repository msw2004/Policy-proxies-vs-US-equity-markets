"""Guardrails for the claims that would be most damaging to get wrong."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmeq import datasets as ds                                    # noqa: E402
from pmeq.config import MARKETS                                    # noqa: E402

# ETF bars are vendor data and are not committed; the tests that need them skip
# on a fresh clone and run in full once `python -m pmeq.datasets refresh` has run.
HAVE_PRICES = (ds.DATA_RAW / "prices" / "SPY.csv").exists()
needs_prices = pytest.mark.skipif(
    not HAVE_PRICES, reason="run `python -m pmeq.datasets refresh` to fetch ETF bars")
from pmeq.stats_tools import (                                     # noqa: E402
    bh_fdr, circular_block_permutation, detect_jumps, incremental_r2, nw_lags,
    ols_hac,
)


# ------------------------------------------------------------------ look-ahead
def test_forward_vol_uses_only_future_returns():
    r = pd.Series([0.01, -0.02, 0.05, -0.01, 0.0, 0.03, -0.04, 0.02, 0.01, -0.03],
                  index=pd.date_range("2024-01-01", periods=10, freq="D"))
    fwd = ds.forward_realized_vol(r, horizon=3, annualize=False)
    for t in range(len(r) - 3):
        assert fwd.iloc[t] == pytest.approx(r.iloc[t + 1:t + 4].std())
    assert fwd.iloc[-3:].isna().all()


def test_forward_vol_is_insensitive_to_the_contemporaneous_return():
    r = pd.Series(np.random.default_rng(0).normal(0, 0.01, 40),
                  index=pd.date_range("2024-01-01", periods=40, freq="D"))
    base = ds.forward_realized_vol(r, 5, annualize=False)
    bumped = r.copy()
    bumped.iloc[20] += 10.0
    after = ds.forward_realized_vol(bumped, 5, annualize=False)
    assert after.iloc[20] == pytest.approx(base.iloc[20])   # not in its own window
    assert after.iloc[19] != pytest.approx(base.iloc[19])   # but is in day 19's


def test_polymarket_bars_land_after_the_us_close():
    """The whole alignment argument in datasets.py depends on this being true."""
    raw = pd.read_csv(ds.DATA_RAW / "polymarket" / "fed_hike_2026.csv")
    et = pd.to_datetime(raw["t"], unit="s", utc=True).dt.tz_convert(ds.MARKET_TZ)
    after_close = ((et.dt.hour > 16) | ((et.dt.hour == 16) & (et.dt.minute > 0))).mean()
    assert after_close > 0.95


# ------------------------------------------------------------------- estimation
def test_bh_fdr_matches_statsmodels():
    from statsmodels.stats.multitest import multipletests

    p = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
    assert np.allclose(bh_fdr(p).values, multipletests(p.values, method="fdr_bh")[1])


def test_incremental_r2_uses_identical_rows():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2024-01-01", periods=200, freq="D")
    y = pd.Series(rng.normal(size=200), index=idx)
    base = pd.DataFrame({"b": rng.normal(size=200)}, index=idx)
    extra = pd.DataFrame({"e": rng.normal(size=200)}, index=idx)
    y.iloc[3] = np.nan
    base.iloc[7, 0] = np.nan
    extra.iloc[11, 0] = np.nan
    out = incremental_r2(y, base, extra)
    assert out["n"] == 197
    assert out["base_model"].nobs == out["full_model"].nobs == 197
    assert out["delta_r2"] >= -1e-12


def test_nw_lags_scales_with_sample_and_is_not_a_fixed_ten():
    assert nw_lags(74) == 3
    assert nw_lags(390) == 5
    assert nw_lags(74) < nw_lags(2000)


def test_ols_hac_reports_all_three_covariances():
    rng = np.random.default_rng(2)
    idx = pd.date_range("2024-01-01", periods=150, freq="D")
    x = pd.DataFrame({"x": rng.normal(size=150)}, index=idx)
    y = pd.Series(0.5 * x["x"] + rng.normal(size=150), index=idx)
    m = ols_hac(y, x)
    for s in (m.tstats, m.tstats_ols, m.tstats_hc3):
        assert "x" in s.index and np.isfinite(s["x"])
    assert m.lags == nw_lags(150)


def test_permutation_shifts_the_signal_and_keeps_its_autocorrelation():
    rng = np.random.default_rng(3)
    n = 400
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    e = rng.normal(size=n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.95 * x[i - 1] + e[i]
    sig = pd.DataFrame({"s": x}, index=idx)
    rolled = pd.DataFrame(np.roll(sig.values, 37, axis=0), index=idx, columns=["s"])
    assert not np.allclose(rolled["s"].values, sig["s"].values)
    assert rolled["s"].autocorr(1) == pytest.approx(sig["s"].autocorr(1), abs=0.02)

    y = pd.Series(rng.normal(size=n), index=idx)
    base = pd.DataFrame({"b": rng.normal(size=n)}, index=idx)
    out = circular_block_permutation(y, base, sig, n_iter=60, seed=0)
    assert 0.0 <= out["p_value"] <= 1.0
    assert np.isfinite(out["detectable_floor"])


def test_detect_jumps_ignores_changes_across_a_quoting_outage():
    idx = list(pd.date_range("2024-01-01", periods=10, freq="D"))
    idx += [idx[-1] + pd.Timedelta(days=12)]
    p = pd.Series([0.30] * 10 + [0.60], index=pd.DatetimeIndex(idx))
    assert len(detect_jumps(p, sigma_mult=0.5, min_pp=0.05)) == 0


# ------------------------------------------------------------------------ data
@needs_prices
def test_price_panel_is_aligned_and_plausible():
    px = ds.load_price_panel()
    assert px.index.is_monotonic_increasing and not px.index.has_duplicates
    assert (px > 0).all().all()
    vol = ds.load_returns().std() * np.sqrt(252)
    assert 0.05 < vol["SPY"] < 0.30
    assert vol["VIXY"] > 0.30


def test_probabilities_are_probabilities():
    for m in MARKETS:
        s = ds.load_polymarket(m.key)
        assert s.between(0, 1).all(), m.key
        assert s.index.is_monotonic_increasing and not s.index.has_duplicates


def test_resolved_contract_settles_near_one():
    s = ds.load_polymarket("gov_shutdown_2025")
    assert s.iloc[-1] > 0.95, "the 2025 shutdown resolved YES"
