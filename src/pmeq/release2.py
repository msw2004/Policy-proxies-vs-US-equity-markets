"""Release 2 - news-based Economic Policy Uncertainty as the comparison proxy.

Two strands, as specified in the brief:

* the **daily** national EPU index, 7-day smoothed;
* the **categorical monthly** EPU sub-indices, matched to each case theme
  (monetary policy / trade policy / sovereign debt).

and both are then compared with Release 1.

A note on the daily strand.  ``datasets.load_epu_daily`` returns ``None`` when the
snapshot is missing.  In the sandbox that produced the published results the daily
CSV could not be retrieved (the fetch layer truncates that 15k-row file in 1992), so
the daily strand is *reported as unavailable* rather than silently skipped, and the
monthly strand carries the comparison.  Re-run ``python -m pmeq.datasets refresh`` on
a networked machine and this module picks the daily series up automatically.

The monthly strand deliberately runs on two windows:

* the **Release 1 window** (11 months, 2025-09..2026-08), which is the like-for-like
  comparison - and on which nothing survives correction; and
* the **full 1993-2026 window** (~400 months), which shows what the same measure
  delivers once it has power.  That contrast is the actual finding of this release.

The window argument is `window='polymarket'` for backwards compatibility, but it is
the *price panel's* span - what Release 1 estimates on - not the union of the
contracts' quote dates.  See `release1_window`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import datasets as ds
from .config import HAC_LAGS_MONTHLY, MARKETS, OUT_TAB, THEMES
from .stats_tools import nw_lags, ols_hac

SMOOTH_DAYS = 7

# target -> (label, kind, months of return data the target spans)
#
# `kind` is load-bearing.  A trailing 12-month volatility at month t is a
# function of returns t-11..t, so regressing it on EPU at month t is a
# *contemporaneous* statement with eleven months of backward overlap - not a
# forecast, however much the R^2 flatters it.  The forward twin is carried
# alongside precisely so the difference is visible in the same table rather than
# left to the reader.
TARGETS = {
    "ret":          ("contemporaneous monthly return",      "contemporaneous", 1),
    "abs_ret":      ("contemporaneous |monthly return|",     "contemporaneous", 1),
    "log_rv12":     ("trailing 12m realised vol (log)",      "contemporaneous", 12),
    "fwd_abs_ret":  ("next month |return|",                  "forward",         1),
    "log_fwd_rv12": ("forward 12m realised vol (log)",       "forward",         12),
}

REGRESSORS = ["dlog_EPU", "log_EPU", "dlog_EPUMONETARY", "log_EPUMONETARY",
              "dlog_EPUTRADE", "log_EPUTRADE", "dlog_EPUSOVDEBT", "log_EPUSOVDEBT"]


def min_obs_for(overlap: int) -> int:
    """Smallest sample that may be regressed on a target spanning ``overlap`` months.

    A target built from an h-month window carries roughly n/h independent
    observations, so the binding requirement is simply that the sample be longer
    than the window - which eleven months are not, against twelve.  The 4x margin
    asks for a handful of independent blocks rather than one; on this data every
    multiplier from 1 to 10 gives identical results, so nothing hinges on the
    exact figure.
    """
    return max(8, 4 * int(overlap))


# --------------------------------------------------------------- monthly market
def monthly_market_panel() -> pd.DataFrame:
    """Monthly SPY returns and two volatility measures, indexed by month."""
    spy = ds.load_spy_monthly()
    px = spy["adj_close"]
    ret = np.log(px).diff()
    df = pd.DataFrame({"ret": ret})
    df["abs_ret"] = df["ret"].abs()
    # 12-month trailing realised volatility, annualised
    df["rv12"] = df["ret"].rolling(12).std() * np.sqrt(12)
    df["log_rv12"] = np.log(df["rv12"])
    # forward-looking targets (no look-ahead in the regressor)
    df["fwd_abs_ret"] = df["abs_ret"].shift(-1)
    df["fwd_rv12"] = df["rv12"].shift(-12)
    df["log_fwd_rv12"] = np.log(df["fwd_rv12"])
    return df


def release1_window() -> tuple[pd.Period, pd.Period]:
    """The months Release 1 actually estimates on, as a closed period interval.

    Not the union of the contracts' quote dates.  That union is dragged eight
    months earlier by ``gov_shutdown_2025``, which quotes from 2025-01 but which
    Release 1 excludes from its correlation work because only ~20 trading days
    overlap the price panel.  Taking the union would make the "like-for-like
    comparison with Release 1" cover months Release 1 never sees, and drop the
    last month it does - so the window is defined by the price panel, which is
    what Release 1 estimates on.
    """
    px = ds.load_price_panel()
    return (pd.Period(px.index.min(), freq="M"), pd.Period(px.index.max(), freq="M"))


def epu_frame() -> pd.DataFrame:
    """Monthly EPU headline plus the three categorical sub-indices, in logs."""
    cols = {"EPU": ds.load_epu_monthly()}
    for s in ds.CATEGORICAL_EPU:
        cols[s] = ds.load_categorical_epu(s)
    df = pd.DataFrame(cols)
    for c in list(df.columns):
        # sub-indices contain exact zeros in sparse early months; +1 keeps logs finite
        df[f"log_{c}"] = np.log(df[c].clip(lower=0) + 1.0)
        df[f"dlog_{c}"] = df[f"log_{c}"].diff()
    return df


# ------------------------------------------------------------------ daily strand
def daily_strand() -> dict:
    """7-day smoothed daily EPU against daily returns, when the snapshot exists."""
    epu = ds.load_epu_daily()
    if epu is None:
        return {
            "available": False,
            "reason": (
                "Daily EPU snapshot absent. The retrieval channel available in this "
                "environment truncates All_Daily_Policy_Data.csv at ~2,900 rows "
                "(mid-1992), so no observations overlap the 2025-09..2026-08 price "
                "window. Run `python -m pmeq.datasets refresh` where the host can "
                "reach policyuncertainty.com."
            ),
            "table": pd.DataFrame(),
        }

    rets = ds.load_returns()
    sm = epu.rolling(SMOOTH_DAYS).mean()
    lvl = np.log(sm).reindex(rets.index).ffill(limit=3)
    d = lvl.diff()

    rows = []
    for tk in rets.columns:
        df = pd.DataFrame({"ret": rets[tk], "dlog_epu": d}).dropna()
        if len(df) < 60:
            continue
        m = ols_hac(df["ret"], df[["dlog_epu"]], lags=10)
        rows.append({
            "asset": tk, "n": m.nobs,
            "corr": df["ret"].corr(df["dlog_epu"]),
            "beta": m.params.get("dlog_epu", np.nan),
            "t": m.tstats.get("dlog_epu", np.nan),
            "p": m.pvalues.get("dlog_epu", np.nan),
            "r2": m.r2,
        })
    return {"available": True, "table": pd.DataFrame(rows), "smoothed": sm}


# ------------------------------------------------------- categorical / monthly
def monthly_regressions(window: str = "full") -> pd.DataFrame:
    """Regress monthly market outcomes on EPU levels and changes.

    ``window='full'`` uses everything from 1993-03 (first full SPY monthly return);
    ``window='polymarket'`` restricts to the months covered by Release 1.
    """
    mkt = monthly_market_panel()
    epu = epu_frame()
    df = mkt.join(epu, how="inner")

    if window == "polymarket":
        lo, hi = release1_window()
        df = df.loc[(df.index >= lo) & (df.index <= hi)]

    rows = []
    for tgt, (label, kind, overlap) in TARGETS.items():
        for reg in REGRESSORS:
            sub = df[[tgt, reg]].dropna()
            # A target spanning h months carries roughly n/h independent
            # observations, so a sample shorter than a few multiples of h cannot
            # speak to it at all.  Without this gate the 11-month window happily
            # regresses a 12-month overlapping volatility on EPU and reports
            # t = -11.2 (against t_OLS = -2.1) from a HAC estimator whose
            # bandwidth equals its sample size.  That number is an artefact of
            # the estimator, not a finding, and it would have been the loudest
            # cell in the release.
            if len(sub) < min_obs_for(overlap):
                continue
            # A target built from an h-month window shares h-1 months with its own
            # neighbour, so the residuals are autocorrelated by construction out to
            # h-1 whatever the sample size.  The plug-in bandwidth is a function of
            # n alone and does not know that: on n=389 it returns 5 for a 12-month
            # overlapping target, and the resulting t-statistics are 17-38% too
            # large.  Overlap sets the floor; the plug-in rule takes over above it.
            L = HAC_LAGS_MONTHLY
            if L == "auto":
                L = max(nw_lags(len(sub)), overlap - 1)
            try:
                m = ols_hac(sub[tgt], sub[[reg]], lags=L)
            except ValueError:
                continue
            rows.append({
                "window": window, "target": tgt, "target_label": label,
                "target_kind": kind, "overlap_months": overlap,
                "regressor": reg, "n": m.nobs,
                "beta": m.params.get(reg, np.nan),
                "t": m.tstats.get(reg, np.nan),
                "p": m.pvalues.get(reg, np.nan),
                "t_ols": m.tstats_ols.get(reg, np.nan),
                "hac_lags": m.lags,
                "r2": m.r2,
                "underpowered": m.nobs < 30,
            })
    return pd.DataFrame(rows)


def theme_matched_table() -> pd.DataFrame:
    """For each case theme, the categorical index that covers the same policy domain."""
    rows = []
    for m in MARKETS:
        th = THEMES[m.theme]
        rows.append({
            "market": m.key, "theme": m.theme, "theme_label": th["label"],
            "categorical_epu": th["epu_categorical"] or "(none published)",
            "emv_component": th["emv_component"] or "(none published)",
            "volume_usd": m.volume_usd,
        })
    return pd.DataFrame(rows)


def proxy_agreement() -> pd.DataFrame:
    """Do the two proxies measure the same thing?

    Monthly-averaged Polymarket probability vs. the theme-matched categorical EPU,
    over whatever months they share - which is 7 to 9, depending on the contract.
    These are descriptive only, and the sample size is reported beside every
    correlation so nobody reads them as evidence.
    """
    epu = epu_frame()
    rows = []
    for m in MARKETS:
        cat = THEMES[m.theme]["epu_categorical"]
        if cat is None:
            continue
        p = ds.load_polymarket(m.key)
        pm = p.groupby(pd.PeriodIndex(p.index, freq="M")).mean()
        joined = pd.DataFrame({"p": pm, "epu": epu[f"log_{cat}"]}).dropna()
        if len(joined) < 4:
            continue
        dj = joined.diff().dropna()
        rows.append({
            "market": m.key, "theme": m.theme, "categorical_epu": cat,
            "n_months": len(joined),
            "corr_levels": joined["p"].corr(joined["epu"]),
            "corr_changes": dj["p"].corr(dj["epu"]) if len(dj) > 2 else np.nan,
        })
    return pd.DataFrame(rows)


def short_window_inflation() -> pd.DataFrame:
    """Every cell the short window calls significant, priced against 400 months.

    **On the shipped data this returns an empty frame**, because the short window
    certifies nothing (0 of 24 cells survive FDR).  It is kept because it is the
    right question to ask of any window that *does* claim something - an earlier
    and wrong version of this release used a 19-month window that certified four
    cells, and this table is what showed them to be inflated 2.6x to 25x.  See
    ``detectability_on_short_window`` for the question that is live here.

    Two cautions are built into the output rather than left to the reader.

    First, a ratio of coefficients is only interpretable when the denominator is
    itself identified.  Where the full-sample estimate's interval covers zero the
    ratio has no finite confidence set - it can be made arbitrarily large, or flip
    sign, anywhere inside that interval - so ``inflation_x`` is suppressed and the
    cell is marked ``full_is_identified = False``.  Quote the range over the
    identified cells only.

    Second, "bigger" is not the same as "significantly bigger".  ``z_diff`` tests
    beta_short - beta_full against the two standard errors, which is the claim
    actually being made.
    """
    from .stats_tools import bh_fdr

    short = monthly_regressions("polymarket")
    full = monthly_regressions("full")
    if not len(short) or not len(full):
        return pd.DataFrame()

    short = short.copy()
    short["p_fdr"] = bh_fdr(short["p"])
    sig = short[short["p_fdr"] < 0.10]
    fi = full.set_index(["target", "regressor"])

    rows = []
    for _, r in sig.iterrows():
        key = (r["target"], r["regressor"])
        if key not in fi.index:
            continue
        g = fi.loc[key]
        se_s = abs(r["beta"] / r["t"]) if r["t"] else np.nan
        se_f = abs(g["beta"] / g["t"]) if g["t"] else np.nan
        identified = abs(g["t"]) > 1.96
        se_diff = float(np.sqrt(se_s ** 2 + se_f ** 2))
        rows.append({
            "target": r["target"], "target_label": r["target_label"],
            "target_kind": r["target_kind"], "regressor": r["regressor"],
            "n_short": int(r["n"]), "beta_short": r["beta"], "t_short": r["t"],
            "n_full": int(g["n"]), "beta_full": g["beta"], "t_full": g["t"],
            "full_is_identified": identified,
            # only meaningful when the denominator is distinguishable from zero
            "inflation_x": (r["beta"] / g["beta"]) if identified and g["beta"] else np.nan,
            "sign_flip": (r["beta"] * g["beta"]) < 0,
            # is the gap itself significant, or just visible?
            "z_diff": (r["beta"] - g["beta"]) / se_diff if se_diff else np.nan,
        })
    cols = ["target", "target_label", "target_kind", "regressor", "n_short",
            "beta_short", "t_short", "n_full", "beta_full", "t_full",
            "full_is_identified", "inflation_x", "sign_flip", "z_diff"]
    if not rows:
        # a header-only frame, not a blank file: an empty CSV raises EmptyDataError
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    # identified cells first, then by how big the discrepancy actually is
    return out.sort_values(
        ["full_is_identified", "z_diff"],
        ascending=[False, False], key=lambda s: s.abs() if s.name == "z_diff" else s)


def detectability_on_short_window() -> pd.DataFrame:
    """Could Release 1's window have found what the full sample finds?

    ``short_window_inflation`` answers "what does the short window get wrong"
    only when the short window claims something.  Here it claims nothing, so the
    informative question is the other one: take each relationship the full sample
    *does* establish, and ask what chance eleven months had of detecting it.

    Three things about these numbers.

    *The alpha matters and is stated.*  ``power_at_alpha05`` is the conventional
    single-test figure.  But the short window was screened with BH-FDR at q=0.10
    over 24 cells, whose strictest rung is 0.10/24 - a far harder target.  Both
    are reported, and the FDR column is the one that corresponds to the test
    actually run.  Quoting only the 5% figure would overstate the short window's
    chances several-fold.

    *The effect sizes are winner's-cursed.*  They are the R-squareds of cells that
    survived FDR on the full sample, so they are biased upward, so the power is
    optimistic.  That errs in the direction that makes the short window look
    better than it is, which is the safe direction for the argument here.

    *The effective n is indicative only.*  It is a lag-1 estimate from ten or
    eleven points; treat the ordering, not the decimal.
    """
    from .stats_tools import bh_fdr, effective_n, power_for_effect

    full = monthly_regressions("full").copy()
    if not len(full):
        return pd.DataFrame()
    full["p_fdr"] = bh_fdr(full["p"])
    established = full[full["p_fdr"] < 0.10]

    mkt = monthly_market_panel()
    epu = epu_frame()
    df = mkt.join(epu, how="inner")
    lo, hi = release1_window()
    short = df.loc[(df.index >= lo) & (df.index <= hi)]

    # the strictest rung of the BH ladder over the cells the short window screens
    n_cells_screened = max(1, len(monthly_regressions("polymarket")))
    alpha_fdr = 0.10 / n_cells_screened

    rows = []
    for _, r in established.iterrows():
        sub = short[[r["target"], r["regressor"]]].dropna()
        n_short = len(sub)
        n_eff = effective_n(sub[r["target"]], sub[r["regressor"]]) if n_short >= 10 else n_short
        rows.append({
            "target_label": r["target_label"], "target_kind": r["target_kind"],
            "regressor": r["regressor"],
            "r2_full": r["r2"], "n_full": int(r["n"]),
            "n_short": n_short,
            "n_short_effective": round(n_eff, 1),
            "estimable_on_short_window": n_short >= min_obs_for(r["overlap_months"]),
            "power_at_alpha05": power_for_effect(r["r2"], max(n_short, 4), k_base=0),
            "power_at_alpha05_eff": power_for_effect(
                r["r2"], max(int(n_eff), 4), k_base=0),
            "power_at_fdr_screen": power_for_effect(
                r["r2"], max(n_short, 4), k_base=0, alpha=alpha_fdr),
        })
    return pd.DataFrame(rows).sort_values("r2_full", ascending=False)


def comparison_vs_release1() -> pd.DataFrame:
    """Side-by-side: what each proxy delivers, and on how much data."""
    try:
        r1 = pd.read_csv(OUT_TAB / "r1_correlations.csv")
    except FileNotFoundError:
        r1 = pd.DataFrame()

    full = monthly_regressions("full")
    pmw = monthly_regressions("polymarket")

    rows = []
    if len(r1):
        sig = r1[r1["p_hc3_fdr"] < 0.10]
        rows.append({
            "proxy": "Polymarket implied probability",
            "frequency": "daily",
            "sample": "2025-09-03..2026-08-31",
            "n_obs_max": int(r1["n"].max()),
            "n_pairs_tested": len(r1),
            "n_pairs_signif_fdr10": len(sig),
            "best_abs_t": float(r1["t_hc3"].abs().max()),
            "median_abs_t": float(r1["t_hc3"].abs().median()),
        })
    for label, tab in (("EPU (Release 1 window)", pmw), ("EPU (full 1993-2026)", full)):
        if not len(tab):
            rows.append({"proxy": label, "frequency": "monthly", "sample": "no estimable cells",
                         "n_obs_max": 0, "n_pairs_tested": 0, "n_pairs_signif_fdr10": 0,
                         "best_abs_t": np.nan, "median_abs_t": np.nan})
            continue
        tab = tab.copy()
        from .stats_tools import bh_fdr
        tab["p_fdr"] = bh_fdr(tab["p"])
        rows.append({
            "proxy": label,
            "frequency": "monthly",
            "sample": f"{tab['n'].min()}-{tab['n'].max()} months",
            "n_obs_max": int(tab["n"].max()),
            "n_pairs_tested": len(tab),
            "n_pairs_signif_fdr10": int((tab["p_fdr"] < 0.10).sum()),
            "best_abs_t": float(tab["t"].abs().max()),
            "median_abs_t": float(tab["t"].abs().median()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- run
def run() -> dict:
    daily = daily_strand()
    full = monthly_regressions("full")
    pmw = monthly_regressions("polymarket")
    themes = theme_matched_table()
    agree = proxy_agreement()
    comp = comparison_vs_release1()
    infl = short_window_inflation()
    power = detectability_on_short_window()

    monthly = pd.concat([pmw, full], ignore_index=True)
    monthly.to_csv(OUT_TAB / "r2_monthly_regressions.csv", index=False)
    themes.to_csv(OUT_TAB / "r2_theme_mapping.csv", index=False)
    agree.to_csv(OUT_TAB / "r2_proxy_agreement.csv", index=False)
    comp.to_csv(OUT_TAB / "r2_comparison_vs_release1.csv", index=False)
    infl.to_csv(OUT_TAB / "r2_short_window_inflation.csv", index=False)
    power.to_csv(OUT_TAB / "r2_short_window_power.csv", index=False)
    if daily["available"]:
        daily["table"].to_csv(OUT_TAB / "r2_daily_epu.csv", index=False)

    return {"daily": daily, "monthly_full": full, "monthly_pm": pmw,
            "themes": themes, "agreement": agree, "comparison": comp,
            "inflation": infl, "power": power}


if __name__ == "__main__":
    out = run()
    print("daily strand available:", out["daily"]["available"])
    if not out["daily"]["available"]:
        print(" ", out["daily"]["reason"])
    print()
    print("=== full-sample monthly regressions (top by |t|) ===")
    f = out["monthly_full"]
    print(f.reindex(f["t"].abs().sort_values(ascending=False).index).head(14).round(4).to_string(index=False))
    print()
    print("=== Polymarket-window monthly regressions ===")
    print(out["monthly_pm"].round(4).to_string(index=False))
    print()
    print("=== proxy agreement ===")
    print(out["agreement"].round(3).to_string(index=False))
    print()
    print("=== comparison ===")
    print(out["comparison"].round(3).to_string(index=False))
