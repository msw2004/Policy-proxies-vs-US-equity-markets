"""Run Release 3 end to end and print a summary.

    python scripts/run_release3.py            # 500 placebo draws (~2 min)
    python scripts/run_release3.py 1500       # the reported figure

Release 3 stops correlating raw probabilities with returns and instead maps each
contract onto factors with an economic reading, aggregates them into one index,
and asks whether that index says anything about *risk* that the usual volatility
controls do not already say. Every headline increment is put through a
circular-shift placebo, because at daily frequency with persistent regressors a
respectable-looking increment is exactly what a spurious regression produces.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from pmeq import datasets as ds, plots, release3  # noqa: E402
from pmeq.config import OUT_FIG, OUT_TAB  # noqa: E402


def main() -> None:
    pd.set_option("display.width", 220)
    n_placebo = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    try:
        ds.load_prices("SPY")
    except ds.PriceDataMissing as exc:
        print(exc)
        raise SystemExit(1)

    print(f"placebo draws: {n_placebo}")
    out = release3.run(n_placebo=n_placebo)
    cpui = out["cpui"]

    print("\n" + "=" * 78)
    print("PANEL CONSTRUCTION")
    print("=" * 78)
    print(f"CPUI method: {cpui.attrs['method']}")
    print(f"contracts in the balanced rectangle: {out['panel'].attrs['contracts']}")
    print(f"days: {len(cpui)}   from {cpui.index[0].date()} to {cpui.index[-1].date()}")
    print()
    print(out["roster"].round(4).to_string(index=False))
    print("\n`shift_in_sd` means the same thing in both rows only if `roster_constant`"
          "\nis True - otherwise it confounds a change in uncertainty with a change in"
          "\nwhich contracts are being averaged.")

    print("\n" + "=" * 78)
    print("INCREMENTAL PREDICTIVE POWER over (trailing RV, VIXY, |return|)")
    print("=" * 78)
    pred = out["predictive"]
    print(pred[["horizon", "signal_set", "term", "n", "beta", "t", "p",
                "r2_base", "r2_full", "delta_r2"]].round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("HOW MUCH OF EACH INCREMENT IS JUST A SHARED TREND?")
    print("=" * 78)
    tr = out["trend"]
    print(tr.round(4).to_string(index=False))
    print("\nagg_entropy correlates +0.84 with elapsed time on this window. The"
          "\nvolatility baseline spans no trend, so without `trend` in it the index"
          "\nis paid for reproducing a drift. Everything below has it in.")

    print("\n" + "=" * 78)
    print("CIRCULAR-SHIFT PLACEBO  <- the test that decides")
    print("=" * 78)
    pl = out["placebo"]
    print(pl[["horizon", "signal_set", "n", "delta_r2", "placebo_mean_delta_r2",
              "detectable_floor", "placebo_p", "placebo_p_fdr", "n_shifts",
              "exact_null"]].round(4).to_string(index=False))
    print("\n`detectable_floor` is the 90th percentile of the null - the smallest"
          "\nincrement this test could call significant at the 10% it is read at."
          "\n`exact_null` means every distinct circular shift was enumerated, so the"
          "\np-value is exact rather than a Monte Carlo estimate.")
    print(f"\nsurviving raw 10%:  {int(pl['survives_raw_10pct'].sum())} of {len(pl)}")
    print(f"surviving FDR 10%:  {int(pl['survives_fdr_10pct'].sum())} of {len(pl)}")
    surv = pl[pl["survives_fdr_10pct"]]
    if len(surv):
        print(surv[["horizon", "signal_set", "delta_r2", "placebo_p_fdr"]]
              .round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("WINDOW, CONTRACT SET, OR ROSTER?")
    print("=" * 78)
    print(out["robustness"].round(4).to_string(index=False))
    print("\nB vs C isolates the window; A vs C isolates the contract set.")

    print("\n" + "=" * 78)
    print("HOW MUCH DOES THE PANEL-SELECTION CONSTANT MATTER?")
    print("=" * 78)
    print(out["rectangle"].round(4).to_string(index=False))
    print("\nmin_days is a free constant and nothing downstream prices the choice.")

    print("\n" + "=" * 78)
    print("WHAT THE 'VOLUME-WEIGHTED AGGREGATE' ACTUALLY IS")
    print("=" * 78)
    print(out["weights"].round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("IS IT CARRIED BY A HANDFUL OF DAYS?")
    print("=" * 78)
    inf = out["influence"]
    print(inf.round(4).to_string(index=False))
    worst = inf["delta_r2_change"].abs().max()
    print(f"\nlargest single-day effect on delta R-squared: {worst:.4f} "
          f"against a full-sample {inf.loc[0, 'delta_r2']:.4f}")

    print("\n" + "=" * 78)
    print("CONTEMPORANEOUS RISK DESCRIPTION (weaker claim)")
    print("=" * 78)
    print(out["contemporaneous"].round(4).to_string(index=False))

    figs = plots.run_release3_figs()
    print(f"\nwrote {len(figs)} figures to {OUT_FIG}")
    print(f"wrote {len(list(OUT_TAB.glob('r3_*.csv')))} tables to {OUT_TAB}")


if __name__ == "__main__":
    main()
