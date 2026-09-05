"""Run Release 4 end to end and print a summary.

    python scripts/run_release4.py            # 500 draws; the null is enumerated
    python scripts/run_release4.py 1500

Release 4 puts Release 3's specification on ~390 months of the Baker-Bloom-Davis-Kost
EMV tracker, with every correction Release 3 needed applied from the start, and then
asks what a 159-day sample could ever have detected.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from pmeq import datasets as ds, release4  # noqa: E402
from pmeq.config import OUT_TAB  # noqa: E402


def main() -> None:
    pd.set_option("display.width", 230)
    n_placebo = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    try:
        ds.load_spy_monthly()
    except ds.PriceDataMissing as exc:
        print(exc)
        raise SystemExit(1)

    out = release4.run(n_placebo=n_placebo)

    print("=" * 78)
    print("DOES THE TRACKER TRACK? (check this before reading anything else)")
    print("=" * 78)
    print(out["validation"].round(4).to_string(index=False))
    print("\nEMV overall correlates 0.46 with realised volatility, which is the"
          "\npremise of the whole release. EMV *trade* correlates -0.02 - it does not"
          "\ntrack volatility at all, so its null result below is not a surprise.")

    print("\n" + "=" * 78)
    print("HOW MUCH OF EACH INCREMENT IS A SHARED TREND?")
    print("=" * 78)
    tr = out["trend"]
    print(tr[["target_label", "signal_set", "n", "delta_r2_no_trend",
              "delta_r2_with_trend", "trend_free_increment_retained",
              "increment_grew_with_trend_control"]].round(4).to_string(index=False))
    print("\nThis is the control for what overturned Release 3, where a linear time"
          "\nindex removed 85-99% of every increment. Here it removes ~0% from the EMV"
          "\ncells: on 390 months those series are stationary and trendless."
          "\n\n`increment_grew_with_trend_control` is a warning flag, not a pass. For"
          "\nheadline EPU the increment MORE THAN DOUBLES when the trend is added,"
          "\nwhich is what a regressor entangled with a drift looks like - log_EPU is a"
          "\nunit root correlating +0.65 with time. Treat that cell with suspicion.")

    print("\n" + "=" * 78)
    print("INCREMENTAL EXPLANATORY POWER over (trailing vol, |return|, trend)")
    print("=" * 78)
    p = out["predictive"]
    print(p.reindex(p["t"].abs().sort_values(ascending=False).index)[
        ["target_label", "target_kind", "signal_set", "term", "n", "beta", "t",
         "hac_lags", "delta_r2"]].head(12).round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("CIRCULAR-SHIFT PLACEBO  <- the test that decides")
    print("=" * 78)
    pl = out["placebo"]
    print(pl[["target_label", "target_kind", "signal_set", "n", "delta_r2",
              "detectable_floor", "placebo_p", "placebo_p_fdr", "n_shifts",
              "exact_null"]].round(4).to_string(index=False))
    print(f"\nsurviving raw 10%:  {int(pl['survives_raw_10pct'].sum())} of {len(pl)}")
    print(f"surviving FDR 10%:  {int(pl['survives_fdr_10pct'].sum())} of {len(pl)}")
    fwd = pl[pl["target_kind"] == "forward"]
    print(f"  ... of which forward-looking: "
          f"{int(fwd['survives_fdr_10pct'].sum())} of {len(fwd)}")

    print("\n" + "=" * 78)
    print("*** CAN YOU ACTUALLY TRADE IT? THE PUBLICATION LAG ***")
    print("=" * 78)
    pl2 = out["publication_lag"]
    print(pl2[["signal_set", "signal_lag_months", "implementable", "delta_r2", "t",
               "placebo_p", "share_of_lag0_retained"]].round(4).to_string(index=False))
    print("\nEMV for month t is built from newspapers dated within t - so there is no"
          "\nlook-ahead in the strict sense - but it is not RELEASED until several days"
          "\ninto t+1, by which time part of the target month has happened. Lag 0 is"
          "\nnot implementable. Lag 1 is the conservative bound a person could have"
          "\ntraded, and the effect decays with a roughly one-month half-life.")

    print("\n" + "=" * 78)
    print("OUT OF SAMPLE - expanding window, one step ahead")
    print("=" * 78)
    print(out["oos"].round(4).to_string(index=False))
    print("\nThis is the only genuine out-of-sample test in the study, and it is what"
          "\nsettles the question. At lag 0 the signal earns +7.7% OOS R-squared. At"
          "\nthe implementable lag it earns essentially nothing.")

    print("\n" + "=" * 78)
    print("IS IT FOUR FINDINGS OR ONE?")
    print("=" * 78)
    rd = out["redundancy"]
    print(rd.round(4).to_string(index=False))
    print(f"\njoint increment from all four: {rd.attrs.get('joint_delta_r2', float('nan')):.4f}"
          f"   largest |t| in the joint model: "
          f"{rd.attrs.get('max_abs_t_in_joint', float('nan')):.2f}")
    print("Four cells clear the FDR screen. Given each other, none of them stands up."
          "\nThat is one finding, not four.")

    print("\n" + "=" * 78)
    print("IS IT A HANDFUL OF CRISES?")
    print("=" * 78)
    print(out["crisis"].round(4).to_string(index=False))
    print("\n=== and does it hold across the sample? ===")
    print(out["subsamples"].round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("DOES THE VERDICT DEPEND ON THE HAC BANDWIDTH?")
    print("=" * 78)
    lg = out["lags"]
    cols = [c for c in ("target_label", "signal_set", "term_shown", "overlap",
                        "lags_used", "t_at_1", "t_at_5", "t_at_10", "t_at_20",
                        "t_at_30") if c in lg.columns]
    print(lg[cols].round(3).to_string(index=False))
    print("\nRelease 2 established the overlap floor is necessary but not sufficient."
          "\nWhere t keeps falling from `floor_h1` to `3x`, read the largest bandwidth.")

    print("\n" + "=" * 78)
    print("WHAT COULD RELEASE 3'S SAMPLE HAVE SEEN?")
    print("=" * 78)
    pw = out["power"]
    eff = pw.attrs.get("release3_n_eff")
    print(f"Release 3: n = {pw.attrs.get('release3_n')}, "
          f"effective n = {eff:.0f}" if eff else "")
    show = [c for c in ("target", "signal_set", "delta_r2_long", "partial_r2",
                        "power_at_long_n", "power_at_release3_n",
                        "power_at_release3_n_eff", "power_at_release3_n_fdr",
                        "n_needed_for_80pct_power")
            if c in pw.columns]
    print(pw[show].round(4).to_string(index=False))
    print("\nEffect sizes are the ones that survived on the long sample, so they are"
          "\nbiased upward and this power is optimistic - it flatters Release 3.")

    print("\n" + "=" * 78)
    print("CROSS-RELEASE SUMMARY (forward-looking targets only)")
    print("=" * 78)
    print(out["summary"].round(4).to_string(index=False))

    print(f"\nwrote {len(list(OUT_TAB.glob('r4_*.csv')))} tables to {OUT_TAB}")


if __name__ == "__main__":
    main()
