"""Release 4 - the same question on a sample that can answer it.

Baker, Bloom, Davis & Kost (*Journal of Financial Economics* 175(C), 2026,
doi:10.1016/j.jfineco.2025.104187) publish the Equity Market Volatility (EMV)
tracker: a newspaper-based measure of volatility-relevant news flow, monthly from
1985, with policy-specific components.  That gives ~390 usable months against
Release 3's 159 trading days.

The specification is deliberately the same *shape* as Release 3 - a persistent
uncertainty index, an autoregressive volatility baseline it has to beat, HAC
errors, a circular-shift placebo - so a difference in verdict is attributable to
power rather than to a change of model.

Every correction Release 3 needed is applied here from the start rather than after
the fact:

* a **linear trend in the baseline**, because that is what turned Release 3 from a
  finding into a null.  On this sample it changes almost nothing - the EMV series
  correlate about 0.00 with elapsed time over 390 months, against +0.84 for
  Release 3's index over eight - and that contrast is itself worth reporting.  A
  trending regressor was a short-window artefact, not a property of news-based
  uncertainty measures.
* an **exactly enumerated placebo** rather than a sampled one.
* **BH-FDR across the whole grid**, as in Releases 1 and 2.
* a **HAC bandwidth floored at the target's overlap**, plus an explicit
  sensitivity, because Release 2 established that the floor is necessary but not
  sufficient against AR-persistent residuals.
* a **stationarity verdict beside every cell**, because a levels regression of two
  drifting series is what produced Release 3's backwards VIXY sign.

**Two findings, and they must be reported together.**

There is a real effect: log EMV overall adds 5.96% to R-squared for next month's
absolute return over an autoregressive volatility baseline, exact placebo p =
0.0028, and it holds out of sample at +7.7% OOS R-squared over 270 expanding-window
forecasts.  It is not a crisis artefact, not a trend artefact, not a bandwidth
artefact, and a richer AR baseline does not absorb it.

And it is not usable.  EMV for month t is not *released* until several days into
t+1, so the lag-0 specification needs a number nobody has yet.  At the conservative
implementable lag the increment falls by 69% and the out-of-sample gain goes to
**+0.04%**.  ``publication_lag`` and ``out_of_sample`` are those tables.

Two further things the FDR grid alone would misreport.  Four cells clear the screen
on the headline target, but conditioning each on the others leaves no |t| above
1.87 - it is one effect counted four times, which ``redundancy`` shows.  And the
headline-EPU cell should be discounted separately: it is a unit root correlating
+0.65 with elapsed time, its increment *doubles* when the trend control is added,
and the circular-shift placebo is anti-conservative against stochastic trends
specifically.

The release closes with the question Release 3 could not answer about itself:
given the effect sizes the long sample identifies, what chance did a 159-day sample
ever have of detecting one?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import datasets as ds
from .config import N_PLACEBO, OUT_TAB, RANDOM_SEED
from .stats_tools import (
    bh_fdr, circular_block_permutation, effective_n, incremental_r2, nw_lags,
    ols_hac, power_for_effect, stationarity, zscore,
)

EMV_SERIES = list(ds.EMV_TRACKER)
EPU_SERIES = list(ds.CATEGORICAL_EPU)

# target -> (label, kind, months of return data the target spans)
TARGETS = {
    "fwd_abs_ret":  ("next month |return|",              "forward",         1),
    "log_fwd_rv12": ("realised vol over next 12m (log)", "forward",         12),
    "log_rv12":     ("trailing 12m realised vol (log)",  "contemporaneous", 12),
}

SIGNAL_SETS = {
    "EMV overall":     ["log_EMVOVERALLEMV"],
    "EMV monetary":    ["log_EMVMONETARYPOL"],
    "EMV trade":       ["log_EMVTRADEPOLEMV"],
    "EMV policy pair": ["log_EMVMONETARYPOL", "log_EMVTRADEPOLEMV"],
    "EPU headline":    ["log_EPU"],
    "EPU categorical": ["log_EPUMONETARY", "log_EPUTRADE", "log_EPUSOVDEBT"],
}


def hac_lags_for(overlap: int, n: int, multiple: float = 1.0) -> int:
    """Newey-West bandwidth with a floor set by the target's overlap.

    A target spanning h months shares h-1 of them with its neighbour, so residuals
    are autocorrelated by construction whatever n is; the plug-in rule sees only n
    and returns 5 here.  ``multiple`` scales the floor, because Release 2 showed
    that ``h-1`` closes most of the gap but not all of it against AR-persistent
    residuals - ``lag_sensitivity`` reports what the extra lags do.
    """
    return max(nw_lags(n), int(round(multiple * (overlap - 1))))


def base_cols_for(target: str) -> list[str]:
    """What the news measure has to beat: the market's own recent history, and time.

    ``log_rv12`` cannot be its own control, so the contemporaneous target drops it.
    """
    cols = ["abs_ret", "trend"] if target == "log_rv12" else ["log_rv12", "abs_ret", "trend"]
    return cols


def monthly_panel() -> pd.DataFrame:
    """Market outcomes, EMV components and categorical EPU on one monthly index."""
    spy = ds.load_spy_monthly()["adj_close"]
    ret = np.log(spy).diff()

    df = pd.DataFrame({"ret": ret})
    df["abs_ret"] = df["ret"].abs()
    df["rv12"] = df["ret"].rolling(12).std() * np.sqrt(12)
    df["log_rv12"] = np.log(df["rv12"])
    df["fwd_abs_ret"] = df["abs_ret"].shift(-1)
    df["log_fwd_rv12"] = df["log_rv12"].shift(-12)

    for s in EMV_SERIES:
        v = ds.load_emv(s)
        df[s] = v
        # the components contain exact zeros in sparse months; +1 keeps logs finite
        df[f"log_{s}"] = np.log(v.clip(lower=0) + 1.0)
    for s in EPU_SERIES:
        v = ds.load_categorical_epu(s)
        df[f"log_{s}"] = np.log(v.clip(lower=0) + 1.0)
    df["log_EPU"] = np.log(ds.load_epu_monthly())
    df["trend"] = np.arange(len(df), dtype=float) / len(df)
    return df


def emv_validation() -> pd.DataFrame:
    """BBD-Kost's own claim: EMV should track realised volatility. Check it first.

    If the tracker does not correlate with realised volatility at all on this
    sample, nothing downstream is worth reading - so this runs before the tests
    rather than as an afterthought.  The stationarity verdict rides along because
    every regression below is in levels.
    """
    df = monthly_panel().dropna(subset=["rv12"])
    signals = [f"log_{s}" for s in EMV_SERIES] + [f"log_{s}" for s in EPU_SERIES]
    signals += ["log_EPU"]
    others = ["log_rv12", "log_fwd_rv12", "abs_ret", "fwd_abs_ret"]

    rows = []
    for col in signals + others:
        # `col` is itself one of the reference columns for two of the rows, and a
        # duplicated label makes `sub[col]` a DataFrame rather than a Series
        need = list(dict.fromkeys([col, "log_rv12", "abs_ret", "trend"]))
        sub = df[need].dropna()
        if len(sub) < 60:
            continue
        st = stationarity(sub[col])
        rows.append({
            "series": col,
            "role": "signal" if col in signals else (
                "target" if col in ("log_fwd_rv12", "fwd_abs_ret") else "baseline"),
            "n": len(sub),
            "corr_with_log_rv12": sub[col].corr(sub["log_rv12"]),
            "corr_with_abs_ret": sub[col].corr(sub["abs_ret"]),
            "corr_with_time": sub[col].corr(sub["trend"]),
            "stationarity": st["verdict"],
            "adf_p": st["adf_p"], "kpss_p": st["kpss_p"],
        })
    return pd.DataFrame(rows)


def incremental_tests(n_placebo: int = N_PLACEBO) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Incremental explanatory power of policy-news measures over an AR baseline."""
    df = monthly_panel()

    rows, placebo_rows = [], []
    for tgt, (label, kind, overlap) in TARGETS.items():
        base_cols = base_cols_for(tgt)
        for name, cols in SIGNAL_SETS.items():
            sub = df[[tgt] + base_cols + cols].dropna()
            if len(sub) < 60:
                continue
            lags = hac_lags_for(overlap, len(sub))
            y, base = sub[tgt], sub[base_cols]
            sig = sub[cols].apply(zscore)
            try:
                inc = incremental_r2(y, base, sig, lags=lags)
            except ValueError:
                continue
            m = inc["full_model"]
            for c in cols:
                rows.append({
                    "target": tgt, "target_label": label, "target_kind": kind,
                    "signal_set": name, "term": c, "n": inc["n"],
                    "beta": m.params.get(c, np.nan),
                    "t": m.tstats.get(c, np.nan), "p": m.pvalues.get(c, np.nan),
                    "hac_lags": lags,
                    "r2_base": inc["r2_base"], "r2_full": inc["r2_full"],
                    "delta_r2": inc["delta_r2"], "delta_adj_r2": inc["delta_adj_r2"],
                    "wald_p": inc["wald_p"],
                })
            perm = circular_block_permutation(
                y, base, sig, n_iter=n_placebo, lags=lags, seed=RANDOM_SEED)
            placebo_rows.append({
                "target": tgt, "target_label": label, "target_kind": kind,
                "signal_set": name, "n": inc["n"], "delta_r2": inc["delta_r2"],
                "placebo_mean_delta_r2": perm["null_mean"],
                "detectable_floor": perm["detectable_floor"],
                "placebo_q95_delta_r2": perm["null_q95"],
                "placebo_p": perm["p_value"],
                "n_shifts": perm["n_shifts"], "exact_null": perm["exact"],
            })
    placebo = pd.DataFrame(placebo_rows)
    if len(placebo):
        # eighteen cells, six overlapping signal sets: correct, as Releases 1-3 do
        placebo["placebo_p_fdr"] = bh_fdr(placebo["placebo_p"])
        placebo["survives_raw_10pct"] = placebo["placebo_p"] < 0.10
        placebo["survives_fdr_10pct"] = placebo["placebo_p_fdr"] < 0.10
    return pd.DataFrame(rows), placebo


def publication_lag(n_placebo: int = N_PLACEBO) -> pd.DataFrame:
    """**The decisive table in this release.**

    EMV for month *t* is built from newspapers published during month *t*, so
    nothing in it post-dates *t* and there is no look-ahead in the strict sense.
    But the index is not *released* until several days into month *t+1*, by which
    time a meaningful part of the target month has already happened.  A forecast
    that needs a number nobody has yet is not a forecast.

    The strict lag - use EMV for *t-1* to predict |return| in *t+1* - is the
    conservative bound, and it is the one that matters, because it is the only
    version a person could actually have traded.  The effect decays with a
    roughly one-month half-life, so the bound is not close: the headline is
    essentially a contemporaneous relationship with one month of persistence
    attached, not a forecasting result.
    """
    df = monthly_panel()
    base_cols = base_cols_for("fwd_abs_ret")
    rows = []
    for name, cols in SIGNAL_SETS.items():
        for lag in (0, 1, 2, 3):
            sub = df[["fwd_abs_ret"] + base_cols + cols].copy()
            for c in cols:
                sub[c] = sub[c].shift(lag)
            sub = sub.dropna()
            if len(sub) < 60:
                continue
            L = hac_lags_for(1, len(sub))
            sig = sub[cols].apply(zscore)
            try:
                inc = incremental_r2(sub["fwd_abs_ret"], sub[base_cols], sig, lags=L)
            except ValueError:
                continue
            rec = {
                "signal_set": name, "signal_lag_months": lag,
                "implementable": lag >= 1, "n": inc["n"],
                "delta_r2": inc["delta_r2"],
                "t": inc["full_model"].tstats.get(cols[0], np.nan),
            }
            if lag in (0, 1):
                perm = circular_block_permutation(
                    sub["fwd_abs_ret"], sub[base_cols], sig,
                    n_iter=n_placebo, lags=L, seed=RANDOM_SEED)
                rec["placebo_p"] = perm["p_value"]
            rows.append(rec)
    out = pd.DataFrame(rows)
    if len(out):
        base = out[out.signal_lag_months == 0].set_index("signal_set")["delta_r2"]
        out["share_of_lag0_retained"] = out.apply(
            lambda r: r["delta_r2"] / base[r["signal_set"]]
            if base.get(r["signal_set"], 0) > 0 else np.nan, axis=1)
    return out


def out_of_sample(min_train: int = 120) -> pd.DataFrame:
    """A genuine expanding-window forecast test, at both lags.

    Nothing else in this study is estimated out of sample; the placebo and the
    trend control stand in for one.  Here there is enough data to do the real
    thing, and it is worth doing precisely because it makes the publication-lag
    verdict unambiguous rather than a matter of specification taste.

    ``oos_r2`` is 1 - SSE(full)/SSE(baseline) over one-step-ahead forecasts, so
    positive means the signal helped.  ``dm_t`` is a Diebold-Mariano statistic on
    the squared-error differential with HAC errors.
    """
    df = monthly_panel()
    base_cols = base_cols_for("fwd_abs_ret")
    rows = []
    for name, cols in SIGNAL_SETS.items():
        for lag in (0, 1):
            sub = df[["fwd_abs_ret"] + base_cols + cols].copy()
            for c in cols:
                sub[c] = sub[c].shift(lag)
            sub = sub.dropna()
            if len(sub) < min_train + 40:
                continue
            y = sub["fwd_abs_ret"].to_numpy()
            Xb = np.column_stack([np.ones(len(sub)), sub[base_cols].to_numpy()])
            Xf = np.column_stack([Xb, sub[cols].to_numpy()])
            eb, ef = [], []
            for i in range(min_train, len(sub)):
                for X, store in ((Xb, eb), (Xf, ef)):
                    beta, *_ = np.linalg.lstsq(X[:i], y[:i], rcond=None)
                    store.append(y[i] - X[i] @ beta)
            eb, ef = np.asarray(eb), np.asarray(ef)
            d = eb ** 2 - ef ** 2
            m = ols_hac(pd.Series(d), pd.DataFrame(index=range(len(d))),
                        lags=max(1, nw_lags(len(d))))
            rows.append({
                "signal_set": name, "signal_lag_months": lag,
                "implementable": lag >= 1, "n_forecasts": len(d),
                "oos_r2": 1 - (ef ** 2).sum() / (eb ** 2).sum(),
                "dm_t": float(m.tstats.get("const", np.nan)),
            })
    return pd.DataFrame(rows)


def redundancy() -> pd.DataFrame:
    """Are the surviving cells separate findings, or one finding counted repeatedly?

    Four cells clear the FDR screen on next month's |return|, which reads as four
    results.  It is one.  ``log_EMVOVERALLEMV`` and ``log_EMVMONETARYPOL``
    correlate 0.75; the "policy pair" is the monetary component plus a regressor
    that adds nothing; and headline EPU adds nothing once EMV overall is in.  This
    table asks, for each survivor, what it contributes *given the others* - which
    is the question the FDR grid does not ask.
    """
    df = monthly_panel()
    base_cols = base_cols_for("fwd_abs_ret")
    survivors = {
        "EMV overall": "log_EMVOVERALLEMV",
        "EMV monetary": "log_EMVMONETARYPOL",
        "EMV trade": "log_EMVTRADEPOLEMV",
        "EPU headline": "log_EPU",
    }
    cols = list(survivors.values())
    sub = df[["fwd_abs_ret"] + base_cols + cols].dropna()
    L = hac_lags_for(1, len(sub))
    z = sub[cols].apply(zscore)

    rows = []
    for label, c in survivors.items():
        others = [o for o in cols if o != c]
        alone = incremental_r2(sub["fwd_abs_ret"], sub[base_cols], z[[c]], lags=L)
        given = incremental_r2(
            sub["fwd_abs_ret"], pd.concat([sub[base_cols], z[others]], axis=1),
            z[[c]], lags=L)
        rows.append({
            "signal": label, "column": c, "n": alone["n"],
            "delta_r2_alone": alone["delta_r2"],
            "t_alone": alone["full_model"].tstats.get(c, np.nan),
            "delta_r2_given_others": given["delta_r2"],
            "t_given_others": given["full_model"].tstats.get(c, np.nan),
        })
    out = pd.DataFrame(rows)
    joint = incremental_r2(sub["fwd_abs_ret"], sub[base_cols], z, lags=L)
    out.attrs["joint_delta_r2"] = joint["delta_r2"]
    out.attrs["max_abs_t_in_joint"] = float(
        max(abs(joint["full_model"].tstats.get(c, np.nan)) for c in cols))
    return out


def crisis_robustness() -> pd.DataFrame:
    """Is the headline a handful of crises?

    Half the increment does come from high-volatility months, which is worth
    stating plainly - but it survives every cut, and winsorising barely moves it,
    so it is not a few outliers wearing a regression.
    """
    df = monthly_panel()
    base_cols = base_cols_for("fwd_abs_ret")
    col = "log_EMVOVERALLEMV"
    full = df[["fwd_abs_ret"] + base_cols + [col]].dropna()
    yr = full.index.year

    def fit(sub, label):
        if len(sub) < 60:
            return None
        L = hac_lags_for(1, len(sub))
        inc = incremental_r2(sub["fwd_abs_ret"], sub[base_cols],
                             sub[[col]].apply(zscore), lags=L)
        return {"cut": label, "n": inc["n"], "delta_r2": inc["delta_r2"],
                "t": inc["full_model"].tstats.get(col, np.nan)}

    cuts = [(full, "none (published)")]
    q95 = full["fwd_abs_ret"].quantile(0.95)
    cuts.append((full[full["fwd_abs_ret"] < q95], "drop top 5% by target |return|"))
    cuts.append((full[~np.isin(yr, [2008, 2009])], "drop 2008-2009"))
    cuts.append((full[yr != 2020], "drop 2020"))
    cuts.append((full[~np.isin(yr, [2008, 2009, 2020])], "drop 2008-09 and 2020"))
    cuts.append((full[~np.isin(yr, [1998, 2001, 2002, 2008, 2009, 2020])],
                 "drop 1998, 2001-02, 2008-09, 2020"))
    w = full.copy()
    for c in ("fwd_abs_ret", col):
        lo, hi = w[c].quantile([0.01, 0.99])
        w[c] = w[c].clip(lo, hi)
    cuts.append((w, "winsorise 1/99"))

    rows = [r for sub, lab in cuts if (r := fit(sub, lab)) is not None]
    out = pd.DataFrame(rows)
    out["share_of_published"] = out["delta_r2"] / out.loc[0, "delta_r2"]
    return out


def subsample_stability() -> pd.DataFrame:
    """Does the effect hold in both halves, or is it a pre-crisis relic?"""
    df = monthly_panel()
    base_cols = base_cols_for("fwd_abs_ret")
    col = "log_EMVOVERALLEMV"
    full = df[["fwd_abs_ret"] + base_cols + [col]].dropna()
    yr = full.index.year
    spans = [("1994-2009", yr <= 2009), ("2010-2026", yr >= 2010),
             ("1994-2001", yr <= 2001), ("2002-2009", (yr >= 2002) & (yr <= 2009)),
             ("2010-2017", (yr >= 2010) & (yr <= 2017)), ("2018-2026", yr >= 2018)]
    rows = []
    for label, mask in spans:
        sub = full[mask]
        if len(sub) < 60:
            continue
        L = hac_lags_for(1, len(sub))
        inc = incremental_r2(sub["fwd_abs_ret"], sub[base_cols],
                             sub[[col]].apply(zscore), lags=L)
        rows.append({"span": label, "n": inc["n"], "delta_r2": inc["delta_r2"],
                     "t": inc["full_model"].tstats.get(col, np.nan)})
    return pd.DataFrame(rows)


def trend_decomposition() -> pd.DataFrame:
    """How much of each increment is a shared drift?

    This table exists because it is what overturned Release 3, where a linear time
    index removed 85-99% of every increment.  Running it here is the control: if
    the EMV results were the same kind of artefact, this is where it would show.
    """
    df = monthly_panel()
    rows = []
    for tgt, (label, kind, overlap) in TARGETS.items():
        full_base = base_cols_for(tgt)
        no_trend = [c for c in full_base if c != "trend"]
        for name, cols in SIGNAL_SETS.items():
            sub = df[[tgt] + full_base + cols].dropna()
            if len(sub) < 60:
                continue
            lags = hac_lags_for(overlap, len(sub))
            sig = sub[cols].apply(zscore)
            try:
                d0 = incremental_r2(sub[tgt], sub[no_trend], sig, lags=lags)
                d1 = incremental_r2(sub[tgt], sub[full_base], sig, lags=lags)
            except ValueError:
                continue
            a, b = d0["delta_r2"], d1["delta_r2"]
            rows.append({
                "target": tgt, "target_label": label, "signal_set": name,
                "n": d1["n"], "delta_r2_no_trend": a, "delta_r2_with_trend": b,
                # ratio only, and only where the denominator is big enough to
                # mean something - at a ~ 0 it swings wildly and a negative value
                # is not a "share" of anything
                "trend_free_increment_retained": b / a if a > 0.005 else np.nan,
                "increment_grew_with_trend_control": bool(a > 0 and b > a),
            })
    return pd.DataFrame(rows)


def lag_sensitivity() -> pd.DataFrame:
    """Does the verdict depend on the HAC bandwidth?

    Release 2 established that flooring the bandwidth at the overlap closes most of
    the gap but not all of it - the residuals of an overlapping-window regression
    are AR-persistent rather than MA(h-1), so t keeps falling as lags grow.  The
    honest response is to show where it stops falling rather than to pick a number.
    """
    df = monthly_panel()
    rows = []
    for tgt, (label, kind, overlap) in TARGETS.items():
        base_cols = base_cols_for(tgt)
        for name, cols in SIGNAL_SETS.items():
            sub = df[[tgt] + base_cols + cols].dropna()
            if len(sub) < 60:
                continue
            sig = sub[cols].apply(zscore)
            rec = {"target": tgt, "target_label": label, "signal_set": name,
                   "term_shown": cols[0], "n": len(sub), "overlap": overlap,
                   "lags_used": hac_lags_for(overlap, len(sub))}
            # absolute lag counts, so the bandwidth genuinely varies even on a
            # target with no overlap - where `hac_lags_for` returns the plug-in
            # value for every multiplier and a "sensitivity" over multipliers
            # would be the same number four times
            for L in (1, 5, 10, 20, 30):
                try:
                    m = incremental_r2(sub[tgt], sub[base_cols], sig, lags=L)
                except ValueError:
                    continue
                rec[f"t_at_{L}"] = m["full_model"].tstats.get(cols[0], np.nan)
            rows.append(rec)
    return pd.DataFrame(rows)


def release3_effective_n(horizon: int = 10) -> tuple[int, float]:
    """Raw and autocorrelation-adjusted sample size of the Release 3 regression.

    The horizon has to be named.  Release 3 runs 5, 10 and 21 days and they give
    n = 159 / 159 / 149 with effective n of 78 / 69 / 60, so quoting "Release 3's
    sample" without saying which one lets the choice drift toward whichever number
    suits the conclusion.  The default is 10 days, which is where Release 3's
    largest increments sit and therefore the fairest comparison.
    """
    from .release3 import build_factor_panel, composite_index, risk_frame

    panel, _ = build_factor_panel()
    cpui = composite_index(panel)
    rf = risk_frame(horizon)
    df = pd.concat([rf["fwd_rv"], cpui], axis=1).dropna()
    return len(df), effective_n(df.iloc[:, 0], df.iloc[:, 1])


def _n_for_power(partial_r2: float, k: int, target: float = 0.80,
                 k_base: int = 1) -> float:
    if not np.isfinite(partial_r2) or partial_r2 <= 0:
        return np.nan
    for n in range(20, 20001, 10):
        if power_for_effect(partial_r2, n, k, k_base=k_base) >= target:
            return float(n)
    return np.nan


def power_comparison(pred: pd.DataFrame, r3_n: int = 159,
                     r3_n_eff: float | None = None,
                     fdr_alpha: float | None = None) -> pd.DataFrame:
    """What could Release 3's sample have detected, given Release 4's effect sizes?

    Takes each incremental effect the long sample identifies, treats its partial
    R-squared as the truth, and computes the power of an F-test at Release 3's
    sample size - raw and autocorrelation-adjusted, because overlapping volatility
    windows are nowhere near independent.  Low power means Release 3's null was
    uninformative rather than evidence of absence.

    Two honesty notes carried from Release 2's audit.  The effect sizes are the
    ones that *survived* on the long sample, so they are biased upward and the
    power is optimistic - which errs toward making Release 3 look better than it
    was.  And the power is quoted for a single test at 5%, while Release 3
    screened its grid with BH-FDR, a materially harder target.
    """
    rows = []
    for (tgt, name), grp in pred.groupby(["target", "signal_set"]):
        d = float(grp["delta_r2"].iloc[0])
        k = int(grp["term"].nunique())
        n_long = int(grp["n"].iloc[0])
        partial = d / max(1e-9, 1 - grp["r2_base"].iloc[0])
        k_base_long = len(base_cols_for(tgt))
        k_base_r3 = 4                                  # rv21, vixy, abs_ret, trend
        rec = {
            "target": tgt, "signal_set": name, "k_terms": k,
            "n_long_sample": n_long, "delta_r2_long": d, "partial_r2": partial,
            "power_at_long_n": power_for_effect(partial, n_long, k, k_base=k_base_long),
            "power_at_release3_n": power_for_effect(partial, r3_n, k, k_base=k_base_r3),
            "n_needed_for_80pct_power": _n_for_power(partial, k, 0.80, k_base=k_base_r3),
        }
        if r3_n_eff is not None:
            rec["power_at_release3_n_eff"] = power_for_effect(
                partial, max(6, int(round(r3_n_eff))), k, k_base=k_base_r3)
        if fdr_alpha is not None:
            # Release 3 screened with BH-FDR, not a single 5% test.  Quoting only
            # the 5% figure overstates what its sample could have certified.
            rec["power_at_release3_n_fdr"] = power_for_effect(
                partial, r3_n, k, k_base=k_base_r3, alpha=fdr_alpha)
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("delta_r2_long", ascending=False)


FORWARD_TARGETS = {"fwd_abs_ret", "log_fwd_rv12"}


def cross_release_summary() -> pd.DataFrame:
    """One table comparing like with like.

    Only *forward-looking* targets are admitted.  Release 4's largest increments
    come from ``log_rv12``, which is trailing realised volatility - a
    contemporaneous fit, not a forecast - and putting that beside Release 3's
    forward-looking number would flatter the news-based measures for the wrong
    reason.  Signal-set labels are read off the files rather than assumed.
    """
    rows = []
    try:
        r3 = pd.read_csv(OUT_TAB / "r3_placebo.csv")
        for name, grp in r3.groupby("signal_set"):
            best = grp.loc[grp["delta_r2"].idxmax()]
            rows.append({
                "release": "R3 Polymarket", "signal_set": name,
                "target": f"realised vol, next {int(best['horizon'])}d",
                "frequency": "daily",
                "n_obs": int(best["n"]), "delta_r2": float(best["delta_r2"]),
                "placebo_p": float(best["placebo_p"]),
                "placebo_p_fdr": float(best.get("placebo_p_fdr", np.nan)),
                "detectable_floor": float(best.get("detectable_floor", np.nan)),
                "survives_fdr": bool(best.get("survives_fdr_10pct", False)),
            })
    except FileNotFoundError:
        pass
    try:
        r4 = pd.read_csv(OUT_TAB / "r4_placebo.csv")
        r4 = r4[r4["target"].isin(FORWARD_TARGETS)]
        for (name, tgt), grp in r4.groupby(["signal_set", "target"]):
            best = grp.loc[grp["delta_r2"].idxmax()]
            rows.append({
                "release": "R4 news-based", "signal_set": name,
                "target": str(best["target_label"]),
                "frequency": "monthly",
                "n_obs": int(best["n"]), "delta_r2": float(best["delta_r2"]),
                "placebo_p": float(best["placebo_p"]),
                "placebo_p_fdr": float(best.get("placebo_p_fdr", np.nan)),
                "detectable_floor": float(best.get("detectable_floor", np.nan)),
                "survives_fdr": bool(best.get("survives_fdr_10pct", False)),
            })
    except FileNotFoundError:
        pass
    out = pd.DataFrame(rows)
    return out.sort_values("delta_r2", ascending=False) if len(out) else out


# --------------------------------------------------------------------------- run
def run(n_placebo: int = N_PLACEBO) -> dict:
    val = emv_validation()
    pred, placebo = incremental_tests(n_placebo)
    trend = trend_decomposition()
    lags = lag_sensitivity()
    publag = publication_lag(n_placebo)
    oos = out_of_sample()
    redun = redundancy()
    crisis = crisis_robustness()
    subs = subsample_stability()
    try:
        r3_n, r3_eff = release3_effective_n()
    except Exception:                                              # noqa: BLE001
        r3_n, r3_eff = 159, None
    power_fdr_alpha = 0.10 / max(1, len(placebo))
    power = power_comparison(pred, r3_n=r3_n, r3_n_eff=r3_eff,
                             fdr_alpha=power_fdr_alpha)
    power.attrs["release3_n"] = r3_n
    power.attrs["release3_n_eff"] = r3_eff

    val.to_csv(OUT_TAB / "r4_emv_validation.csv", index=False)
    pred.to_csv(OUT_TAB / "r4_incremental.csv", index=False)
    placebo.to_csv(OUT_TAB / "r4_placebo.csv", index=False)
    trend.to_csv(OUT_TAB / "r4_trend_decomposition.csv", index=False)
    lags.to_csv(OUT_TAB / "r4_lag_sensitivity.csv", index=False)
    publag.to_csv(OUT_TAB / "r4_publication_lag.csv", index=False)
    oos.to_csv(OUT_TAB / "r4_out_of_sample.csv", index=False)
    redun.to_csv(OUT_TAB / "r4_redundancy.csv", index=False)
    crisis.to_csv(OUT_TAB / "r4_crisis_robustness.csv", index=False)
    subs.to_csv(OUT_TAB / "r4_subsamples.csv", index=False)
    power.to_csv(OUT_TAB / "r4_power.csv", index=False)
    summary = cross_release_summary()
    summary.to_csv(OUT_TAB / "r4_cross_release_summary.csv", index=False)

    return {"validation": val, "predictive": pred, "placebo": placebo,
            "trend": trend, "lags": lags, "power": power, "summary": summary,
            "publication_lag": publag, "oos": oos, "redundancy": redun,
            "crisis": crisis, "subsamples": subs}
