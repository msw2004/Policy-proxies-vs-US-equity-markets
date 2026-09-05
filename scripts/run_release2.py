"""Run Release 2 end to end and print a summary.

    python scripts/run_release2.py

Release 2 swaps the prediction-market proxy for the news-based EPU index and asks
the same question of it.  The finding is the contrast between the two windows, so
both are printed side by side.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from pmeq import datasets as ds, plots, release2  # noqa: E402
from pmeq.config import OUT_FIG, OUT_TAB  # noqa: E402


def main() -> None:
    pd.set_option("display.width", 200)

    try:
        ds.load_spy_monthly()
    except ds.PriceDataMissing as exc:
        print(exc)
        raise SystemExit(1)

    out = release2.run()

    print("=" * 78)
    print("DAILY STRAND")
    print("=" * 78)
    if out["daily"]["available"]:
        print(out["daily"]["table"].round(4).to_string(index=False))
    else:
        print("UNAVAILABLE - reported as such rather than silently substituted:")
        print("  " + out["daily"]["reason"])

    print("\n" + "=" * 78)
    print("MONTHLY REGRESSIONS - FULL SAMPLE (1993-2026)")
    print("=" * 78)
    f = out["monthly_full"]
    top = f.reindex(f["t"].abs().sort_values(ascending=False).index)
    print(top[["target_label", "regressor", "n", "beta", "t", "t_ols", "hac_lags",
               "r2"]].head(12).round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("MONTHLY REGRESSIONS - POLYMARKET WINDOW (the like-for-like comparison)")
    print("=" * 78)
    p = out["monthly_pm"]
    if len(p):
        pt = p.reindex(p["t"].abs().sort_values(ascending=False).index)
        print(pt[["target_label", "regressor", "n", "beta", "t", "r2",
                  "underpowered"]].head(10).round(4).to_string(index=False))
        print(f"\ncells estimated: {len(p)}   max months available: {int(p['n'].max())}")
    else:
        print("no estimable cells on this window")

    print("\n" + "=" * 78)
    print("DO THE TWO PROXIES MEASURE THE SAME THING?")
    print("=" * 78)
    print(out["agreement"].round(3).to_string(index=False))
    print("\nNote: n_months is in single or low double digits - descriptive only.")

    print("\n" + "=" * 78)
    print("WHAT THE SHORT WINDOW CLAIMS, PRICED AGAINST THE FULL SAMPLE")
    print("=" * 78)
    infl = out["inflation"]
    if len(infl):
        print(infl[["target_label", "regressor", "n_short", "beta_short",
                    "n_full", "beta_full", "full_is_identified", "inflation_x",
                    "sign_flip", "z_diff"]].round(4).to_string(index=False))
        print("\n`inflation_x` is blank where the full-sample coefficient is itself"
              "\nindistinguishable from zero - a ratio to noise has no finite"
              "\nconfidence set.  `z_diff` tests the gap rather than displaying it.")
    else:
        print("The short window certifies nothing: 0 cells survive FDR at 10%.")
        print("So the question is the other one, below.")

    print("\n" + "=" * 78)
    print("COULD ELEVEN MONTHS HAVE FOUND WHAT 400 MONTHS FINDS?")
    print("=" * 78)
    pw = out["power"]
    print(pw[["target_label", "regressor", "r2_full", "n_short",
              "n_short_effective", "estimable_on_short_window",
              "power_at_alpha05", "power_at_alpha05_eff",
              "power_at_fdr_screen"]].round(3).to_string(index=False))
    print(f"\nmedian power, single test at alpha=0.05:   "
          f"{pw['power_at_alpha05'].median():.3f}")
    print(f"  ... at the Bartlett effective n:         "
          f"{pw['power_at_alpha05_eff'].median():.3f}")
    print(f"median power against the FDR screen actually applied: "
          f"{pw['power_at_fdr_screen'].median():.3f}")
    print(f"cells even estimable on this window: "
          f"{int(pw['estimable_on_short_window'].sum())} of {len(pw)}")
    print("\nThe FDR column is the one that matches the test the short window was"
          "\nput through; the 5% figures are the conventional single-test reference.")

    print("\n" + "=" * 78)
    print("RELEASE 1 vs RELEASE 2")
    print("=" * 78)
    print(out["comparison"].round(3).to_string(index=False))

    print("\n" + "=" * 78)
    print("THEME MAPPING")
    print("=" * 78)
    print(out["themes"].to_string(index=False))

    figs = plots.run_release2_figs()
    print(f"\nwrote {len(figs)} figures to {OUT_FIG}")
    print(f"wrote {len(list(OUT_TAB.glob('r2_*.csv')))} tables to {OUT_TAB}")


if __name__ == "__main__":
    main()
