"""Run Release 1 end to end and print a summary.

    python scripts/run_release1.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from pmeq import datasets as ds, plots, release1  # noqa: E402
from pmeq.config import OUT_FIG, OUT_TAB  # noqa: E402


def main() -> None:
    pd.set_option("display.width", 200)

    try:
        ds.load_prices("SPY")
    except ds.PriceDataMissing as exc:
        print(exc)
        raise SystemExit(1)

    print("=" * 78)
    print("DATA INVENTORY")
    print("=" * 78)
    print(ds.data_inventory().to_string(index=False))

    print("\n" + "=" * 78)
    print("CONTEMPORANEOUS CO-MOVEMENT")
    print("=" * 78)
    out = release1.run()
    corr = out["corr"]
    print(corr[["market", "asset", "n", "corr_full", "t_ols", "t_hc3", "t_beta_hac",
                "p_hc3_fdr"]].head(10).round(4).to_string(index=False))
    print(f"\npairs tested: {len(corr)}   "
          f"significant after FDR(10%) on HC3: {int((corr['p_hc3_fdr'] < 0.10).sum())}")

    print("\n" + "=" * 78)
    print("EVENT STUDY")
    print("=" * 78)
    print(f"probability-jump events detected: {len(out['events'])}")
    car = out["car"]
    tail = car[car.window_end == 5].reindex(
        car[car.window_end == 5]["t"].abs().sort_values(ascending=False).index)
    print(tail[["market", "asset", "n_events", "car_window", "car_pct", "t", "p_fdr",
                "pre_share_of_move"]].head(8).round(4).to_string(index=False))
    print("\nNote: column `car_window` is the cumulative window, not an h-day response;"
          "\n`pre_share_of_move` is the fraction of the move that lands BEFORE the jump.")

    print("\n" + "=" * 78)
    print("GRANGER CAUSALITY (both directions)")
    print("=" * 78)
    g = out["granger"]
    best = (g.groupby(["market", "asset"])
             .agg(n=("n", "max"),
                  p_prob_leads=("p_prob_leads_market_fdr", "min"),
                  p_market_leads=("p_market_leads_prob_fdr", "min"))
             .reset_index().sort_values("p_prob_leads"))
    print(best.head(8).round(4).to_string(index=False))
    print(f"\nsmallest FDR-adjusted p in either direction: "
          f"{min(g['p_prob_leads_market_fdr'].min(), g['p_market_leads_prob_fdr'].min()):.3f}")

    figs = plots.run_release1_figs()
    print(f"\nwrote {len(figs)} figures to {OUT_FIG}")
    print(f"wrote {len(list(OUT_TAB.glob('r1_*.csv')))} tables to {OUT_TAB}")


if __name__ == "__main__":
    main()
