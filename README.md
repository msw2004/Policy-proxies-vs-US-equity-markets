# Do prediction markets say anything usable about US equities?

**Release 1** of a four-release study on quantitative proxies for public leaning on US
fiscal, monetary and trade policy. This release covers the prediction-market strand:
Polymarket implied probabilities against US equity and rates ETFs.

The short answer: **they co-move, sharply and with the right signs — but they do not
lead.** Twelve of twenty-five contract–asset pairs survive a false-discovery
correction, and every significant sign is the one theory predicts. Nothing survives in
either direction of a Granger test, and the design turns out to be structurally unable
to establish who moves first. Both results are below, with the reason.

---

## What was tested

Seven contracts, selected by keyword search of the Polymarket Gamma API across five
policy themes named in the brief, then ranked on traded volume:

| Contract | Theme | Volume (USD) |
|---|---|---:|
| Sept-2026 FOMC: no change | monetary | 16,181,392 |
| Sept-2026 FOMC: +25bp | monetary | 14,337,501 |
| Fed rate hike in 2026 | monetary | 8,206,364 |
| US government shutdown in 2025 | fiscal | 3,512,315 |
| US recession by end of 2026 | growth | 1,717,659 |
| US–Korea trade deal before 2027 | trade | 59,657 |
| US defaults on debt by 2027 | sovereign debt | 16,228 |

Paired against **SPY, TLT, XLF, XLI and VIXY** — broad equity, long duration,
financials, industrials, and an implied-volatility proxy.

Sample: **2025-09-03 → 2026-08-31, 250 trading days.** That one-year window is the
binding constraint on everything here.

---

## Results

### 1. Contemporaneous co-movement — strong, and correctly signed

| Contract | Asset | n | corr | β | t (OLS) | t (HC3) | p, FDR |
|---|---|--:|--:|--:|--:|--:|--:|
| Sept-2026 +25bp | VIXY | 75 | 0.293 | 0.147 | 2.62 | 3.84 | 0.002 |
| Sept-2026 +25bp | SPY | 75 | −0.307 | −0.046 | −2.76 | −3.76 | 0.002 |
| Sept-2026 no change | SPY | 74 | 0.266 | 0.036 | 2.34 | 3.29 | 0.009 |
| US recession 2026 | XLI | 202 | −0.211 | −0.124 | −3.05 | −2.65 | 0.041 |
| Fed hike 2026 | VIXY | 162 | 0.233 | 0.182 | 3.02 | 2.64 | 0.041 |
| Sept-2026 no change | VIXY | 74 | −0.220 | −0.098 | −1.91 | −2.58 | 0.041 |

**12 of 25 pairs** significant after Benjamini–Hochberg at 10%. Rising hike odds →
equities down, implied volatility up, long bonds down; the mirror "no change" contract
moves everything the other way. The two thin contracts (US–Korea trade at $60k, debt
default at $16k) show nothing, which is unsurprising: 21–32% of their daily changes are
exactly zero.

### 2. Who moves first — the design cannot say

Bidirectional Granger tests at lags 1–5: **nothing survives correction in either
direction** (smallest FDR-adjusted p = 0.979). Two structural reasons, and they matter
more than the test:

- The Polymarket daily bar is stamped at **00:00 UTC — 19:00/20:00 New York time**,
  three to four hours *after* the equity close. A same-day correlation is therefore
  between a return and a probability that had the whole afternoon to absorb it.
- In the event study, an average of **38%** of the cumulative abnormal move lands
  *before* the probability jumps.

Read Release 1 as evidence of tight **same-day co-movement**, and nothing stronger.
Establishing direction needs intraday data, which this design does not have.

### 3. Event study — descriptive only

33 probability-jump events across seven contracts, 3–9 per contract, with overlapping
windows. Nothing survives correction. The tables report the cumulative window
(`car_window`), not an "h-day response", and carry `pre_share_of_move` so the
pre-event drift is visible rather than buried.

---

## Three methodological choices worth knowing about

**The covariance estimator changes the answer by two orders of magnitude.** Daily
return regressions here have *negatively* autocorrelated scores, so Newey–West
*shrinks* the standard error instead of widening it. An arbitrary `maxlags=10` on
n = 74 turns an OLS p-value of 0.022 into 2×10⁻⁷. This repo uses the plug-in bandwidth
`floor(4·(n/100)^(2/9))`, reports **OLS, HC3 and HAC side by side**, and applies the FDR
correction to HC3 — the appropriate headline for a contemporaneous daily regression.

**Jumps measured across a quoting outage are excluded.** Two contracts stopped quoting
for 9–13 days in April 2026. The first print afterwards looks like a large one-day
move but is an accumulated multi-week move; pairing it with a single day's return is
meaningless. `detect_jumps(max_stale_days=4)` drops those.

**SPY cannot be its own benchmark.** The event study uses a market model, which would
return identically zero abnormal returns for the benchmark asset. SPY is handled with a
constant-mean model instead.

---

## Running it

```bash
pip install -r requirements.txt
python -m pmeq.datasets refresh    # one-off: fetch the ETF bars (needs network)
python scripts/run_release1.py     # full analysis + figures
pytest tests/                      # 12 guardrail tests
```

The `refresh` step is required once on a fresh clone. Polymarket implied probabilities
come from a public API and **are** committed under `data/raw/polymarket/`; the ETF daily
bars are third-party vendor data and are **not** redistributed here, so
`data/raw/prices/` ships empty. After the one-off fetch the whole analysis runs offline
and reproduces byte-for-byte from the snapshots.

Without that step the runner exits with a one-line instruction and the two
price-dependent tests skip (`11 passed, 1 skipped`) rather than failing.

Results land in `outputs/tables/*.csv` and `outputs/figures/*.png`.

## Layout

```
src/pmeq/
  config.py       paths, contract registry (with CLOB token ids), theme map
  datasets.py     local loaders + live refresh layer
  stats_tools.py  HAC/HC3 regression, stationarity, Granger, event study,
                  circular-shift placebo, BH-FDR, power
  release1.py     the analysis
  plots.py        figures
scripts/run_release1.py
tests/            look-ahead, FDR, permutation mechanics, data sanity
data/raw/polymarket/  committed probability snapshots (public API)
data/raw/prices/      empty; populated by `python -m pmeq.datasets refresh`
outputs/          tables and figures
```

`config.py` records every contract's CLOB token id, so the exact sample can be
re-fetched later. `datasets.py` and `stats_tools.py` are the study's shared layers and
are included whole; they carry loaders and tests used by Releases 2–4, which are not in
this repository.

## Data provenance

| Series | Source | In this repo |
|---|---|---|
| Implied probabilities | Polymarket CLOB `prices-history`, daily fidelity | committed |
| Contract metadata | Polymarket Gamma `/events`, `/public-search` | committed (`config.py`) |
| ETF daily bars | Yahoo Finance via `yfinance` | fetched, not redistributed |

## Caveats

- **250 trading days.** The single biggest limitation. A longer panel is the highest-value extension.
- **Prediction-market bars post-date the close**, so no same-day result establishes direction.
- **3–9 events per contract** with overlapping windows: the CAR tests have almost no power either way.
- **Two contracts are very thin** and behave accordingly.

## The other three releases

Release 2 adds the Baker/Bloom/Davis news-based EPU index and its categorical
sub-indices; Release 3 turns raw probabilities into economically meaningful factors and
tests a composite policy-uncertainty index against forward realised volatility, with a
circular-shift placebo; Release 4 re-estimates the same specification on the
Baker–Bloom–Davis–Kost EMV tracker's ~400 months and asks what a 250-day sample could
ever have detected.

## Licence

MIT — see `LICENSE`.
