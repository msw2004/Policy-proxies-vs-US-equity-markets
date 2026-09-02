"""Release 1 - Polymarket implied probabilities vs. US equity assets.

Three questions, in order:

1. Do probability changes co-move with asset returns at all?   (21-day rolling
   correlation, plus a full-sample regression reported under three covariance
   estimators, because on this data they disagree by two orders of magnitude)
2. When the crowd re-prices sharply, does the market respond?  (event study on
   probability jumps, cumulative abnormal returns from a market model)
3. Who moves first?                                            (bidirectional
   Granger tests on stationary daily changes)

The unit of analysis is (market, asset).  Because that is a lot of pairs, every
p-value that matters is also reported after a Benjamini-Hochberg correction.

Two cautions that the results section has to carry.  First, the Polymarket daily bar
is stamped after the US equity close, so a same-day correlation cannot by itself say
which side moved first - and the event study shows a large share of the move landing
*before* the probability jumps.  Second, with four to nine events per contract the
CAR tests have almost no power, whichever way they come out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import datasets as ds
from .config import (
    BENCHMARK, ESTIMATION_WINDOW, EVENT_WINDOW, HAC_LAGS_DAILY, JUMP_MIN_PP,
    JUMP_SIGMA, MARKETS, MAX_GRANGER_LAG, OUT_TAB, ROLL_WINDOW,
)
from .stats_tools import (
    bh_fdr, detect_jumps, event_study, granger_pair, ols_hac, stationarity,
)

MIN_OVERLAP = 60  # trading days required before a pair is estimated


def build_pair_frame(market_key: str, ticker: str) -> pd.DataFrame:
    """Aligned daily frame: probability, its change, and the asset's log return."""
    prob = ds.load_polymarket(market_key)
    rets = ds.load_returns()
    if ticker not in rets.columns:
        raise KeyError(ticker)
    df = pd.DataFrame({"p": prob}).join(rets[[ticker]].rename(columns={ticker: "ret"}), how="inner")
    df["dp"] = df["p"].diff()
    df["dlogit"] = np.log(df["p"].clip(0.005, 0.995) / (1 - df["p"].clip(0.005, 0.995))).diff()
    return df.dropna(subset=["ret"])


# --------------------------------------------------------------------- (1) corr
def rolling_correlations(window: int = ROLL_WINDOW) -> tuple[pd.DataFrame, dict]:
    rows, paths = [], {}
    crit = 1.96 / np.sqrt(window - 3)  # Fisher-z 5% critical correlation
    for m in MARKETS:
        for tk in m.assets:
            try:
                df = build_pair_frame(m.key, tk).dropna(subset=["dp"])
            except KeyError:
                continue
            if len(df) < MIN_OVERLAP:
                continue
            roll = df["dp"].rolling(window).corr(df["ret"])
            paths[(m.key, tk)] = roll

            full = ols_hac(df["ret"], df[["dp"]], lags=HAC_LAGS_DAILY)
            r_full = df["dp"].corr(df["ret"])
            z = np.arctanh(np.clip(roll.dropna(), -0.999, 0.999))
            # Three covariance estimators are reported because they disagree here.
            # Daily returns are close to serially uncorrelated and the regression
            # scores are *negatively* autocorrelated, so Newey-West shrinks the
            # standard error rather than widening it.  HC3 - heteroskedasticity
            # robust, no serial-correlation adjustment - is the appropriate headline
            # for a contemporaneous daily regression, and it is what the FDR
            # correction is applied to.
            rows.append({
                "market": m.key, "theme": m.theme, "asset": tk, "n": len(df),
                "corr_full": r_full,
                "beta_dp": full.params.get("dp", np.nan),
                "t_ols": full.tstats_ols.get("dp", np.nan),
                "p_ols": full.pvalues_ols.get("dp", np.nan),
                "t_hc3": full.tstats_hc3.get("dp", np.nan),
                "p_hc3": full.pvalues_hc3.get("dp", np.nan),
                "hac_lags": full.lags,
                "t_beta_hac": full.tstats.get("dp", np.nan),
                "p_beta_hac": full.pvalues.get("dp", np.nan),
                "roll_mean": roll.mean(), "roll_sd": roll.std(),
                "roll_min": roll.min(), "roll_max": roll.max(),
                "frac_signif_window": float((roll.abs() > crit).mean()),
                "frac_negative": float((roll < 0).mean()),
                "mean_abs_z": float(z.abs().mean()) if len(z) else np.nan,
            })
    out = pd.DataFrame(rows)
    if len(out):
        out["p_hc3_fdr"] = bh_fdr(out["p_hc3"])
        out = out.sort_values("p_hc3")
    return out, paths


# -------------------------------------------------------------------- (2) event
def run_event_studies() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rets = ds.load_returns()
    mkt = rets[BENCHMARK]
    ev_rows, car_rows, store = [], [], {}

    for m in MARKETS:
        prob = ds.load_polymarket(m.key)
        prob = prob.reindex(rets.index).ffill(limit=3).dropna()
        events = detect_jumps(prob, JUMP_SIGMA, JUMP_MIN_PP)
        if events.empty:
            continue
        for _, e in events.iterrows():
            ev_rows.append({"market": m.key, "theme": m.theme, "date": e["date"].date(),
                            "dp": e["dp"], "direction": e["direction"],
                            "threshold": e["threshold"]})

        for tk in m.assets:
            if tk not in rets.columns:
                continue
            res = event_study(
                rets[tk], mkt, events, EVENT_WINDOW, ESTIMATION_WINDOW,
                mean_adjusted=(tk == BENCHMARK),
            )
            if res.get("n_events", 0) < 3:
                continue
            store[(m.key, tk)] = res
            lo = res["window_lo"]
            for h in (-1, 0, 1, 3, 5):
                car_rows.append({
                    "market": m.key, "theme": m.theme, "asset": tk,
                    "n_events": res["n_events"],
                    # column h of the cumulative path is CAR over [lo, h] - naming it
                    # "horizon h" would wrongly imply an h-day post-event response
                    "car_window": f"[{lo:+d},{h:+d}]", "window_end": h,
                    "car_pct": 100 * res["car"].get(h, np.nan),
                    "t": res["car_t"].get(h, np.nan),
                    "p": res["car_p"].get(h, np.nan),
                    # how much of the move happened *before* the probability jumped
                    "pre_event_car_pct": 100 * res["pre_event_car"],
                    "post_event_car_pct": 100 * res["post_event_car"],
                    "pre_share_of_move": res["pre_share"],
                    "post_only_t": res["post_t"],
                })
    ev_df = pd.DataFrame(ev_rows)
    car_df = pd.DataFrame(car_rows)
    if len(car_df):
        # correct within each window, not only for one of them
        car_df["p_fdr"] = (
            car_df.groupby("window_end")["p"].transform(bh_fdr)
        )
    return ev_df, car_df, store


# ------------------------------------------------------------------- (3) causality
def run_granger(maxlag: int = MAX_GRANGER_LAG) -> tuple[pd.DataFrame, pd.DataFrame]:
    stat_rows, g_rows = [], []
    for m in MARKETS:
        for tk in m.assets:
            try:
                df = build_pair_frame(m.key, tk).dropna(subset=["dp"])
            except KeyError:
                continue
            if len(df) < MIN_OVERLAP:
                continue

            for label, s in (("p_level", df["p"]), ("dp", df["dp"]), (f"ret_{tk}", df["ret"])):
                st = stationarity(s)
                stat_rows.append({"market": m.key, "asset": tk, "series": label, **st})

            g = granger_pair(df["dp"], df["ret"], maxlag=maxlag)
            g.insert(0, "asset", tk)
            g.insert(0, "theme", m.theme)
            g.insert(0, "market", m.key)
            g_rows.append(g)

    gr = pd.concat(g_rows, ignore_index=True) if g_rows else pd.DataFrame()
    if len(gr):
        gr["p_x_causes_y_fdr"] = bh_fdr(gr["p_x_causes_y"])
        gr["p_y_causes_x_fdr"] = bh_fdr(gr["p_y_causes_x"])
        gr = gr.rename(columns={"p_x_causes_y": "p_prob_leads_market",
                                "p_y_causes_x": "p_market_leads_prob",
                                "p_x_causes_y_fdr": "p_prob_leads_market_fdr",
                                "p_market_leads_prob_fdr": "p_market_leads_prob_fdr"})
        gr = gr.rename(columns={"p_y_causes_x_fdr": "p_market_leads_prob_fdr"})
    return pd.DataFrame(stat_rows), gr


def cross_correlation(max_lag: int = 5) -> pd.DataFrame:
    """corr(dp_t, ret_{t+k}) for k in [-max_lag, max_lag]: a direct lead-lag read."""
    rows = []
    for m in MARKETS:
        for tk in m.assets:
            try:
                df = build_pair_frame(m.key, tk).dropna(subset=["dp"])
            except KeyError:
                continue
            if len(df) < MIN_OVERLAP:
                continue
            rec = {"market": m.key, "theme": m.theme, "asset": tk, "n": len(df)}
            for k in range(-max_lag, max_lag + 1):
                rec[f"k={k:+d}"] = df["dp"].corr(df["ret"].shift(-k))
            rows.append(rec)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- run
def run() -> dict:
    corr, roll_paths = rolling_correlations()
    events, car, car_store = run_event_studies()
    stat, granger = run_granger()
    xcorr = cross_correlation()

    corr.to_csv(OUT_TAB / "r1_correlations.csv", index=False)
    events.to_csv(OUT_TAB / "r1_events.csv", index=False)
    car.to_csv(OUT_TAB / "r1_car.csv", index=False)
    stat.to_csv(OUT_TAB / "r1_stationarity.csv", index=False)
    granger.to_csv(OUT_TAB / "r1_granger.csv", index=False)
    xcorr.to_csv(OUT_TAB / "r1_crosscorr.csv", index=False)

    return {
        "corr": corr, "roll_paths": roll_paths, "events": events, "car": car,
        "car_store": car_store, "stationarity": stat, "granger": granger,
        "xcorr": xcorr,
    }


if __name__ == "__main__":
    out = run()
    print(out["corr"].round(4).to_string(index=False))
