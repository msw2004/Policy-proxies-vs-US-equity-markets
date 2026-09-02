"""Estimation utilities shared by all four releases.

Everything here is deliberately conservative: HAC standard errors by default,
stationarity checked before Granger tests, and an inference layer that treats
overlapping windows and short samples as first-class problems rather than
footnotes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.tsa.stattools import adfuller, grangercausalitytests, kpss


# ------------------------------------------------------------------- regression
@dataclass
class OLSResult:
    params: pd.Series
    tstats: pd.Series
    pvalues: pd.Series
    r2: float
    r2_adj: float
    nobs: int
    resid: pd.Series
    model: object
    lags: int = 0
    tstats_ols: pd.Series | None = None
    pvalues_ols: pd.Series | None = None
    tstats_hc3: pd.Series | None = None
    pvalues_hc3: pd.Series | None = None

    def row(self, name: str) -> dict:
        return {
            "coef": self.params.get(name, np.nan),
            "t": self.tstats.get(name, np.nan),
            "p": self.pvalues.get(name, np.nan),
        }


def nw_lags(n: int) -> int:
    """Newey-West plug-in bandwidth, floor(4*(n/100)^(2/9)).

    A *fixed* lag count is not the conservative choice it looks like.  When the
    regression scores are negatively autocorrelated - the normal case for daily
    return regressions - Bartlett weighting shrinks the standard error
    monotonically in the lag count, so an over-long bandwidth manufactures
    significance.  On n=74 an arbitrary maxlags=10 turns an OLS p-value of 0.02
    into 2e-07.  The bandwidth is therefore taken from the sample size.
    """
    return max(1, int(np.floor(4 * (max(n, 10) / 100.0) ** (2.0 / 9.0))))


def ols_hac(
    y: pd.Series, X: pd.DataFrame, lags: int | str = "auto", add_const: bool = True
) -> OLSResult:
    """OLS with Newey-West covariance; ``lags='auto'`` uses the plug-in rule.

    Plain OLS t-statistics are computed alongside and returned in ``tstats_ols``,
    so callers can report both and any HAC-driven inflation stays visible.
    """
    df = pd.concat([y.rename("__y__"), X], axis=1).dropna()
    if len(df) <= X.shape[1] + 2:
        raise ValueError(f"not enough observations: {len(df)}")
    yy = df["__y__"]
    XX = df.drop(columns="__y__")
    if add_const:
        XX = sm.add_constant(XX, has_constant="add")

    L = nw_lags(len(df)) if lags == "auto" else int(lags)
    plain = sm.OLS(yy, XX).fit()
    hc3 = sm.OLS(yy, XX).fit(cov_type="HC3")
    fit = sm.OLS(yy, XX).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    return OLSResult(
        params=fit.params,
        tstats=fit.tvalues,
        pvalues=fit.pvalues,
        r2=float(fit.rsquared),
        r2_adj=float(fit.rsquared_adj),
        nobs=int(fit.nobs),
        resid=pd.Series(fit.resid, index=yy.index),
        model=fit,
        lags=L,
        tstats_ols=plain.tvalues,
        pvalues_ols=plain.pvalues,
        tstats_hc3=hc3.tvalues,
        pvalues_hc3=hc3.pvalues,
    )


def incremental_r2(
    y: pd.Series, base: pd.DataFrame, extra: pd.DataFrame, lags: int | str = "auto"
) -> dict:
    """R^2 gain from adding ``extra`` to ``base``, with a HAC Wald test on the block.

    Both models are estimated on the *same* rows so the R^2 difference is meaningful.
    """
    common = pd.concat([y, base, extra], axis=1).dropna().index
    y_c = y.loc[common]
    b_c = base.loc[common]
    e_c = extra.loc[common]

    m0 = ols_hac(y_c, b_c, lags=lags)
    m1 = ols_hac(y_c, pd.concat([b_c, e_c], axis=1), lags=lags)

    names = [c for c in e_c.columns]
    R = np.zeros((len(names), len(m1.params)))
    for i, nm in enumerate(names):
        R[i, list(m1.params.index).index(nm)] = 1.0
    wald = m1.model.wald_test(R, use_f=False, scalar=True)

    return {
        "n": int(len(common)),
        "r2_base": m0.r2,
        "r2_full": m1.r2,
        "delta_r2": m1.r2 - m0.r2,
        "adj_r2_base": m0.r2_adj,
        "adj_r2_full": m1.r2_adj,
        "delta_adj_r2": m1.r2_adj - m0.r2_adj,
        "wald_chi2": float(np.asarray(wald.statistic).ravel()[0]),
        "wald_p": float(np.asarray(wald.pvalue).ravel()[0]),
        "df": len(names),
        "full_model": m1,
        "base_model": m0,
    }


# ----------------------------------------------------------------- stationarity
def stationarity(series: pd.Series) -> dict:
    """ADF (H0: unit root) and KPSS (H0: stationary) - reported together."""
    s = series.dropna()
    out = {"n": len(s)}
    if len(s) < 20 or s.nunique() < 3:
        return {**out, "adf_p": np.nan, "kpss_p": np.nan, "verdict": "insufficient"}
    try:
        out["adf_p"] = float(adfuller(s, autolag="AIC")[1])
    except Exception:
        out["adf_p"] = np.nan
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out["kpss_p"] = float(kpss(s, regression="c", nlags="auto")[1])
    except Exception:
        out["kpss_p"] = np.nan

    adf_rej = out["adf_p"] < 0.05
    kpss_rej = out["kpss_p"] < 0.05
    out["verdict"] = (
        "stationary" if adf_rej and not kpss_rej
        else "unit root" if (not adf_rej) and kpss_rej
        else "ambiguous"
    )
    return out


# -------------------------------------------------------------------- Granger
def granger_pair(
    x: pd.Series, y: pd.Series, maxlag: int = 5
) -> pd.DataFrame:
    """Bivariate Granger tests in both directions for lags 1..maxlag.

    Returns one row per lag with the p-value of "x does not Granger-cause y" and of
    the reverse.  Series are aligned on their common index and demeaned; the caller
    is responsible for passing stationary transforms (differences, not levels).
    """
    df = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    rows = []
    if len(df) < 10 * maxlag:
        maxlag = max(1, len(df) // 10)
    import warnings

    for lag in range(1, maxlag + 1):
        row = {"lag": lag, "n": len(df)}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:  # x -> y  (statsmodels tests col2 -> col1)
                res = grangercausalitytests(df[["y", "x"]], maxlag=[lag])
                row["p_x_causes_y"] = float(res[lag][0]["ssr_ftest"][1])
            except Exception:
                row["p_x_causes_y"] = np.nan
            try:  # y -> x
                res = grangercausalitytests(df[["x", "y"]], maxlag=[lag])
                row["p_y_causes_x"] = float(res[lag][0]["ssr_ftest"][1])
            except Exception:
                row["p_y_causes_x"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- event study
def detect_jumps(
    prob: pd.Series, sigma_mult: float = 2.0, min_pp: float = 0.03, min_gap: int = 3,
    max_stale_days: int = 4
) -> pd.DataFrame:
    """Days on which the implied probability moved abnormally.

    A jump is a daily change exceeding both ``sigma_mult`` times the full-sample
    standard deviation of daily changes *and* an absolute floor ``min_pp``.  When two
    jumps fall within ``min_gap`` days, only the larger is kept, so overlapping event
    windows do not double-count the same news.

    ``max_stale_days`` drops changes measured across a quoting outage.  Several of
    these contracts stop updating for a week or more; the first quote afterwards
    prints a large "daily" change that is really an accumulated multi-week move, and
    pairing it with a single day's return would be meaningless.
    """
    dp = prob.diff().dropna()
    if dp.empty:
        return pd.DataFrame(columns=["date", "dp", "direction"])
    elapsed = pd.Series(prob.index, index=prob.index).diff().dt.days.reindex(dp.index)
    dp = dp[elapsed <= max_stale_days]
    if dp.empty:
        return pd.DataFrame(columns=["date", "dp", "direction"])
    thresh = max(sigma_mult * dp.std(), min_pp)
    cand = dp[dp.abs() >= thresh].sort_index()

    kept: list[pd.Timestamp] = []
    for dt in cand.index:
        if kept and (dt - kept[-1]).days < min_gap:
            if abs(cand[dt]) > abs(cand[kept[-1]]):
                kept[-1] = dt
            continue
        kept.append(dt)

    out = pd.DataFrame(
        {"date": kept, "dp": cand.loc[kept].values}
    )
    out["direction"] = np.where(out["dp"] > 0, "up", "down")
    out["threshold"] = thresh
    return out.reset_index(drop=True)


def market_model_abnormal(
    asset_ret: pd.Series, mkt_ret: pd.Series, event_date: pd.Timestamp,
    window: tuple[int, int], est_len: int, mean_adjusted: bool = False
) -> pd.Series | None:
    """Abnormal returns around one event, benchmarked on a pre-event estimation window.

    The alpha/beta of a market model are estimated on ``est_len`` days ending just
    before the event window, which keeps the estimation period clear of the event
    itself.  ``mean_adjusted=True`` switches to a constant-mean model - required when
    the asset *is* the benchmark, where a market model would return identically zero
    abnormal returns by construction.
    """
    idx = asset_ret.index
    if event_date not in idx:
        pos_arr = idx.searchsorted(event_date)
        if pos_arr >= len(idx):
            return None
        event_date = idx[pos_arr]
    pos = idx.get_loc(event_date)
    lo, hi = window
    est_end = pos + lo - 1
    est_start = est_end - est_len
    if est_start < 0 or pos + hi >= len(idx):
        return None

    est_slice = slice(est_start, est_end)
    ev = slice(pos + lo, pos + hi + 1)

    if mean_adjusted:
        mu = asset_ret.iloc[est_slice].dropna()
        if len(mu) < 30:
            return None
        ar = asset_ret.iloc[ev] - mu.mean()
    else:
        y = asset_ret.iloc[est_slice]
        x = mkt_ret.iloc[est_slice]
        d = pd.concat([y, x], axis=1).dropna()
        if len(d) < 30:
            return None
        beta, alpha = np.polyfit(d.iloc[:, 1], d.iloc[:, 0], 1)
        ar = asset_ret.iloc[ev] - (alpha + beta * mkt_ret.iloc[ev])

    ar.index = range(lo, hi + 1)
    return ar


def event_study(
    asset_ret: pd.Series,
    mkt_ret: pd.Series,
    events: pd.DataFrame,
    window: tuple[int, int],
    est_len: int,
    sign_align: bool = True,
    mean_adjusted: bool = False,
) -> dict:
    """Average CAR across events, with a cross-sectional t-test at each horizon.

    ``sign_align`` flips the sign of abnormal returns after downward probability
    jumps, so the test asks "does the market move *with* the news" rather than
    averaging offsetting directions to zero.
    """
    ars = []
    for _, ev in events.iterrows():
        ar = market_model_abnormal(
            asset_ret, mkt_ret, ev["date"], window, est_len, mean_adjusted=mean_adjusted
        )
        if ar is None:
            continue
        if sign_align and ev["dp"] < 0:
            ar = -ar
        ars.append(ar)
    if not ars:
        return {"n_events": 0}

    A = pd.DataFrame(ars)
    # cumulate from the start of the window: column k is CAR[window_lo, k]
    car = A.cumsum(axis=1)
    mean_car = car.mean()
    se = car.std(ddof=1) / np.sqrt(len(car))
    tstat = mean_car / se.replace(0, np.nan)
    pval = pd.Series(
        2 * (1 - stats.t.cdf(tstat.abs(), df=max(len(car) - 1, 1))), index=tstat.index
    )
    lo = A.columns.min()
    pre = A.loc[:, [c for c in A.columns if c < 0]].sum(axis=1)
    post = A.loc[:, [c for c in A.columns if c >= 0]].sum(axis=1)
    return {
        "n_events": len(car),
        "aar": A.mean(),
        "car": mean_car,           # column k == CAR[lo, k], NOT the k-day response
        "car_se": se,
        "car_t": tstat,
        "car_p": pval,
        "car_paths": car,
        "window_lo": lo,
        "pre_event_car": float(pre.mean()),
        "post_event_car": float(post.mean()),
        "pre_share": float(abs(pre.mean()) / max(1e-12, abs(pre.mean()) + abs(post.mean()))),
        "post_t": float(post.mean() / (post.std(ddof=1) / np.sqrt(len(post))))
        if post.std(ddof=1) > 0 else np.nan,
    }


# ------------------------------------------------------------ placebo inference
def circular_block_permutation(
    y: pd.Series,
    base: pd.DataFrame,
    signal: pd.DataFrame,
    n_iter: int = 2000,
    lags: int | str = "auto",
    seed: int = 0,
) -> dict:
    """Null distribution of the incremental R^2 under circular shifts of the signal.

    Rotating the regressor block by a random offset preserves its own
    autocorrelation and marginal distribution while destroying any true alignment
    with the dependent variable.  A large observed delta-R^2 that sits inside this
    null is a spurious-regression artefact, not evidence.
    """
    rng = np.random.default_rng(seed)
    obs = incremental_r2(y, base, signal, lags=lags)
    n = len(signal)
    if n < 30:
        return {"observed": obs, "p_value": np.nan, "null": np.array([])}

    null = np.empty(n_iter)
    vals = signal.to_numpy()
    idx = signal.index
    lo, hi = max(5, int(0.05 * n)), n - max(5, int(0.05 * n))
    for i in range(n_iter):
        shift = int(rng.integers(lo, hi)) if hi > lo else 1
        rolled = pd.DataFrame(np.roll(vals, shift, axis=0), index=idx, columns=signal.columns)
        try:
            null[i] = incremental_r2(y, base, rolled, lags=lags)["delta_r2"]
        except Exception:
            null[i] = np.nan
    null = null[~np.isnan(null)]
    p = float((null >= obs["delta_r2"]).mean()) if len(null) else np.nan
    return {
        "observed": obs,
        "p_value": p,
        "null": null,
        "null_mean": float(np.mean(null)) if len(null) else np.nan,
        # the smallest increment this placebo could ever call significant: if the
        # null's 95th percentile is large, the test has no power and a "does not
        # survive" verdict is uninformative rather than evidence of absence
        "detectable_floor": float(np.quantile(null, 0.95)) if len(null) else np.nan,
        "null_q95": float(np.quantile(null, 0.95)) if len(null) else np.nan,
    }


# ------------------------------------------------------------------ misc helpers
def zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * 0.0


def bh_fdr(pvals: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values - the many-pairs problem is real here."""
    p = pvals.dropna().sort_values()
    m = len(p)
    if m == 0:
        return pvals
    adj = (p.values * m / np.arange(1, m + 1)).clip(max=1.0)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    return pd.Series(adj, index=p.index).reindex(pvals.index)


def effective_n(y: pd.Series, x: pd.Series) -> float:
    """Bartlett-style effective sample size for two autocorrelated series.

    n_eff = n * (1 - r1*r2) / (1 + r1*r2) with r1, r2 the lag-1 autocorrelations.
    Overlapping volatility windows and persistent uncertainty indices both have
    r ~ 0.9+, which can shrink 200 daily observations to a couple of dozen
    independent ones.  Quoting power off the raw n would badly overstate what a
    short sample could ever have detected.
    """
    df = pd.concat([y, x], axis=1).dropna()
    if len(df) < 10:
        return float(len(df))
    r1 = df.iloc[:, 0].autocorr(1)
    r2 = df.iloc[:, 1].autocorr(1)
    if not (np.isfinite(r1) and np.isfinite(r2)):
        return float(len(df))
    prod = float(np.clip(r1 * r2, -0.999, 0.999))
    return float(len(df) * (1 - prod) / (1 + prod))


def power_for_effect(
    r2_partial: float, n: int, k_extra: int = 1, alpha: float = 0.05, k_base: int = 1
) -> float:
    """Power of an F-test to detect a given partial R^2 at sample size n.

    ``k_base`` is the number of baseline regressors excluding the constant, so the
    denominator degrees of freedom are n - k_extra - k_base - 1.  Getting this wrong
    biases power upward, which is the direction that would flatter the conclusion.
    """
    df2 = n - k_extra - k_base - 1
    if not np.isfinite(r2_partial) or r2_partial <= 0 or df2 <= 1:
        return np.nan
    f2 = r2_partial / max(1e-12, 1 - r2_partial)
    lam = f2 * n
    df1 = k_extra
    crit = stats.f.ppf(1 - alpha, df1, df2)
    return float(1 - stats.ncf.cdf(crit, df1, df2, lam))
