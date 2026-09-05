# What prediction markets and policy news can tell us about US equities

This repository contains Releases 1 to 3 of a four-part study of quantitative proxies
for public views on US fiscal, monetary, and trade policy.

- **Release 1** examines the prediction market strand by comparing Polymarket implied
  probabilities with US equity and rates ETFs, on 250 trading days.
- **Release 2** puts the same questions to the Baker, Bloom, and Davis news-based
  Economic Policy Uncertainty index and its categorical sub-indices, first on Release
  1's own window and then on the full 1993 to 2026 sample.
- **Release 3** converts the raw probabilities into economically meaningful factors,
  builds a composite policy uncertainty index from them, and tests whether it improves
  a forward volatility forecast.

Release 1 finds that prediction market probabilities and market prices often move
together on the same day, with directions that match theory, but that the daily data
cannot establish which market moves first. Release 2 explains why that result is shaped
the way it is. On eleven months, EPU also finds nothing. On four hundred months, the
same measure and the same specification produce eleven significant relationships. The
limiting factor in Release 1 is the length of the window, not the choice of proxy.

Release 3 finds nothing either, and is the most useful of the three about *why*. Its
first version reported a strong result that turned out to be a shared time trend,
validated by a placebo that a deterministic ramp also passes, on a grid with no
multiplicity correction, from an aggregate that is 82% one contract. The corrected
analysis reports zero surviving cells out of fifteen. What survives the exercise is the
set of checks, not the finding.

**Every quantitative claim below has been through an adversarial re-check that
recomputed it independently.** Three of those re-checks changed a conclusion. Where a
number here differs from an earlier draft, the earlier one was wrong and the section
says so.

---

# Release 1: Polymarket implied probabilities

## What was tested

Seven contracts were selected through keyword searches of the Polymarket Gamma API.
The searches covered the five policy themes in the project brief, and contracts were
then ranked by trading volume.

| Contract | Theme | Volume (USD) |
|---|---|---:|
| Fed September 2026: no change | monetary | 16,181,392 |
| Fed September 2026: +25bp | monetary | 14,337,501 |
| Fed rate hike in 2026 | monetary | 8,206,364 |
| US government shutdown in 2025 | fiscal | 3,512,315 |
| US recession by end of 2026 | growth | 1,717,659 |
| US-Korea trade deal before 2027 | trade | 59,657 |
| US defaults on debt by 2027 | sovereign debt | 16,228 |

The contracts were paired with SPY, TLT, XLF, XLI, and VIXY. Together they cover broad
equities, long-duration bonds, financials, industrials, and a proxy for implied
volatility.

The sample runs from 2025-09-03 to 2026-08-31 and contains 250 trading days. This
one-year window is the main constraint on the analysis.

## Results

### 1. Same-day co-movement

| Contract | Asset | n | corr | β | t (OLS) | t (HC3) | p, FDR |
|---|---|--:|--:|--:|--:|--:|--:|
| Sept-2026 +25bp | VIXY | 75 | 0.293 | 0.147 | 2.62 | 3.84 | 0.004 |
| Sept-2026 +25bp | SPY | 75 | −0.307 | −0.046 | −2.76 | −3.76 | 0.004 |
| Sept-2026 no change | SPY | 74 | 0.266 | 0.036 | 2.34 | 3.29 | 0.013 |
| US recession 2026 | XLI | 202 | −0.211 | −0.124 | −3.05 | −2.65 | 0.046 |
| Fed hike 2026 | VIXY | 162 | 0.233 | 0.182 | 3.02 | 2.64 | 0.046 |
| Sept-2026 no change | VIXY | 74 | −0.220 | −0.098 | −1.91 | −2.58 | 0.049 |

After Benjamini-Hochberg correction at 10%, 12 of the 25 pairs are significant. When
the odds of a rate increase rise, equities and long bonds fall while implied
volatility rises. The "no change" contract moves in the opposite direction. The two
low-volume contracts, the US-Korea trade deal at about $60,000 and US debt default at
about $16,000, show no significant relationship. Their daily probability changes are
exactly zero on 21% to 32% of observations.

### 2. The data do not show which market moves first

Bidirectional Granger tests at lags 1 through 5 produce no significant result after
correction in either direction. The smallest FDR-adjusted p-value is 0.979. Two timing
problems limit what those tests can tell us:

- A Polymarket daily bar is stamped at 00:00 UTC, which is 19:00 or 20:00 in New York.
  That is three to four hours after the equity close. A same-day correlation therefore
  pairs an asset return with a probability observation that had the whole afternoon to
  absorb it.
- In the event study, an average of 38% of the cumulative abnormal move occurs before
  the recorded probability jump.

Release 1 supports a claim of same-day co-movement. It does not support a claim about
direction. That would require intraday data.

### 3. Event study results are descriptive

The event study contains 33 probability jumps across seven contracts, with three to
nine events per contract and some overlapping windows. No result remains significant
after correction. The output tables report the cumulative window as `car_window`, not
an "h-day response". They also include `pre_share_of_move`, which makes pre-event drift
visible.

---

# Release 2: news-based policy uncertainty

Release 2 replaces the prediction market proxy with the Baker, Bloom, and Davis
news-based EPU index and asks the same questions of it. The finding is the contrast
between two windows, so both are estimated and reported side by side.

## What was tested

Monthly SPY outcomes were regressed on EPU levels and first differences, in logs. Five
targets were used, and each is labelled by kind:

| Target | Kind |
|---|---|
| contemporaneous monthly return | contemporaneous |
| contemporaneous absolute monthly return | contemporaneous |
| trailing 12-month realised volatility (log) | contemporaneous |
| next month absolute return | forward |
| forward 12-month realised volatility (log) | forward |

The kind is load-bearing. A trailing 12-month volatility at month *t* is a function of
returns from *t-11* to *t*, so regressing it on EPU at month *t* is a contemporaneous
statement with eleven months of backward overlap. It is not a forecast, however large
the R² looks. The forward twin is carried in the same table so the difference stays
visible rather than being left to the reader.

Eight regressors were used: levels and log differences of the headline index and of the
three categorical sub-indices that FRED publishes, `EPUMONETARY`, `EPUTRADE`, and
`EPUSOVDEBT`.

Each of the seven Release 1 contracts is mapped to a theme and, where one exists, to a
categorical index. Two themes have no published counterpart. The recession and
government shutdown markets have no matching sub-index, which the mapping table records
as `(none published)` rather than silently reassigning them.

## Results

### 1. The daily strand is reported as unavailable

The daily EPU series could not be retrieved in the environment that produced these
results. The retrieval channel truncates `All_Daily_Policy_Data.csv` at roughly 2,900
rows, which ends in mid-1992, so no observation overlaps the price window. The release
reports this as unavailable rather than substituting the monthly series and calling it
a daily result. On a networked machine, `python -m pmeq.datasets refresh` fills the
file in and the code picks it up automatically.

### 2. On Release 1's window, EPU finds nothing either

Restricted to the months Release 1 estimates on, 24 of the 40 regression cells are even
estimable, the largest sample is 11 months, and **no cell survives FDR correction at
10%**. The largest absolute t-statistic is 2.64.

The window is defined as the span of the price panel, which is what Release 1 actually
estimates on. It is not the union of the contracts' quote dates. That union starts
eight months earlier, because one contract quotes from 2025-01 while Release 1 excludes
it from the correlation work, so using it would compare against months Release 1 never
sees.

### 3. On the full sample, the same measure works

| Target | Regressor | n | β | t (HAC) | R² |
|---|---|--:|--:|--:|--:|
| contemporaneous absolute return | log EPU monetary | 400 | 0.0108 | 3.90 | 0.065 |
| trailing 12m realised vol (log) | log EPU sovereign debt | 389 | 0.0793 | 3.50 | 0.069 |
| trailing 12m realised vol (log) | log EPU monetary | 389 | 0.2403 | 3.46 | 0.134 |
| contemporaneous return | Δlog EPU | 401 | −0.0332 | −3.39 | 0.040 |
| next month absolute return | log EPU monetary | 401 | 0.0082 | 3.31 | 0.037 |
| trailing 12m realised vol (log) | log EPU | 390 | 0.3295 | 3.01 | 0.136 |

Across 389 to 402 months, **11 of 40 cells survive FDR at 10%**. The relationships are
modest, with R² between 0.01 and 0.14, and the strongest of them are the overlapping
volatility targets whose kind is contemporaneous rather than forward.

### 4. Could eleven months have found what four hundred months finds?

This is the question the release is built to answer. Taking each full-sample R² as the
true effect size and asking what power an eleven-month sample would have had against
it:

| Measure | Median power |
|---|---:|
| single test at α = 0.05 | 0.093 |
| the same, at the Bartlett effective n | 0.074 |
| against the FDR screen actually applied | 0.010 |

Only 8 of the 11 cells are estimable on the short window at all. The three trailing
12-month volatility targets are not, because a target built from a twelve-month window
cannot be estimated on eleven months of data.

A median power of 0.01 against the screen actually applied means a null result on this
window carries almost no information. Release 1's nulls are consistent with there being
nothing to find, and equally consistent with there being exactly what the full sample
shows.

### 5. Do the two proxies measure the same thing?

| Market | Theme | Categorical EPU | n months | corr, levels | corr, changes |
|---|---|---|--:|--:|--:|
| Fed hike 2026 | monetary | EPUMONETARY | 7 | −0.784 | −0.094 |
| US-Korea trade deal 2027 | trade | EPUTRADE | 8 | −0.511 | −0.480 |
| US debt default 2027 | sovereign debt | EPUSOVDEBT | 8 | −0.596 | 0.068 |
| US government shutdown 2025 | fiscal shutdown | EPUSOVDEBT | 9 | 0.068 | 0.463 |

These overlaps are seven to nine months long. The table is reported as descriptive and
nothing is inferred from it. At these sample sizes the correlations are not
distinguishable from noise, and the sign disagreement between levels and changes is
what one would expect from that.

![Policy-news intensity and market volatility](outputs/figures/f4_epu_vs_vol.png)

---

# Release 3: from raw probabilities to a policy-uncertainty index

Release 1's weakness is that a raw probability has no stable economic meaning. A market
at 0.90 and a market at 0.10 are both *confident*; a market at 0.50 is maximally
*uncertain*. Correlating the level with returns mixes two different objects.

Release 3 maps each contract onto factors that do have a reading — logit level, binary
entropy (how unresolved the question is), flow (`|Δ logit p|`, how much news arrived),
and drift — aggregates them by traded volume with a cross-sectional dispersion term, and
combines them into an equal-weighted composite (CPUI). The composite has no fitted
parameters, so it cannot be accused of being tuned to the sample it is tested on. The
target is the market's *risk level* — realised volatility over the next 5, 10 or 21
days — because direction is close to unforecastable and risk is what policy uncertainty
should plausibly move.

**The result is null. The interesting part is what it took to establish that.**

## The first version of this release was wrong

It reported that aggregate entropy adds 8.9% to R² at five days with a placebo p of
0.004, and called it a hypothesis worth carrying forward. An adversarial re-check found
five defects, every one of which pushed in the direction of a more impressive result:

**The signal is a time trend.** `agg_entropy` correlates **+0.84 with elapsed time**
over the selected window and fails an ADF test. The volatility baseline
(trailing RV, VIXY, |return|) spans no trend, so the index was being paid for
reproducing a drift. Adding a linear time index to the baseline removes 85–99% of every
increment:

| Horizon | Signal | ΔR² without trend | ΔR² with trend | share from trend | t without | t with |
|---|---|--:|--:|--:|--:|--:|
| 5 | agg_entropy | 0.0886 | 0.0049 | 94% | 1.79 | 0.53 |
| 10 | agg_entropy | 0.1509 | 0.0229 | 85% | 2.10 | 1.14 |
| 21 | agg_entropy | 0.1928 | 0.0022 | 99% | 3.21 | 0.24 |
| 21 | CPUI | 0.0382 | 0.0000 | 100% | 1.87 | 0.04 |

**The placebo could not have caught it.** Circularly shifting a *trending* signal
creates a sawtooth with a discontinuity at the wrap point, which is a worse regressor
than the original — so the null sits too low and the test over-rejects. A deterministic
ramp passes it at every horizon; independent random walks passed at roughly 19% against
a nominal 10%. This is why the trend belongs in the baseline rather than being left for
the placebo to police, and a test now asserts the hole is closed.

**`p = 0.004` was not achievable by the design.** There are only ~145 distinct circular
shifts on a 160-day panel, so 500 random draws mostly repeat, and the resolution of the
test is 1/145 ≈ 0.007. The placebo now **enumerates every distinct shift** and reports
an exact p-value using `(r+1)/(m+1)` — which, unlike `(null >= obs).mean()`, can never
return the 0.000 that the old construction-robustness table published.

**Fifteen cells, no multiplicity correction** — while Releases 1 and 2 both correct
across their grids. BH-FDR is applied here now. The signal sets overlap (CPUI and
entropy+flow both contain agg_entropy), and positive dependence is exactly the case
BH is valid and conservative under, so the correction is if anything too gentle.

**The "volume-weighted aggregate across policy domains" is one contract.**

| Contract | Volume (USD) | Weight | corr with the aggregate |
|---|---:|--:|--:|
| Fed rate hike in 2026 | 8,206,364 | 0.821 | **0.993** |
| US recession by end-2026 | 1,717,659 | 0.172 | −0.619 |
| US–Korea trade deal | 59,657 | 0.006 | −0.007 |
| US debt default by 2027 | 16,228 | 0.002 | −0.300 |

The aggregate *is* `fed_hike_2026`, whose probability walks monotonically toward 0.5
across the window — which is where the trend comes from. The other three carry 18% of
the weight between them and two of them are decorative.

## What the corrected analysis finds

Nothing. With the trend controlled, the bandwidth matched to the forecast overlap, the
null enumerated and the grid FDR-corrected:

**0 of 15 cells survive at 10%, before correction as well as after.** The smallest raw
placebo p across the grid is 0.31. The composite index adds 0.02% to R² at 21 days
against a null whose 10% critical value is 3.45%.

![Release 3 placebo](outputs/figures/f5_placebo.png)

The index itself, with the roster shown beneath it so a level move cannot be confused
with a change in membership:

![CPUI](outputs/figures/f6_cpui.png)

## Two things the release does report

**The panel-selection constant matters, and nothing prices it.**
`select_balanced_panel` chooses both the contracts and the window from the data, and the
placebo only rotates the signal inside the already-chosen rectangle. `min_days` of 100,
120 and 150 all select the same 4-contract rectangle, so 150 is not fine-tuned — but
180 selects a different 3-contract rectangle and flips the sign of *t* at two of the
three horizons. A result whose direction depends on an undocumented constant is not a
result, and the sensitivity table ships so that is visible.

**A levels regression here gets the sign backwards.** CPUI against log VIXY in levels
gives β = −0.060, t = −3.56: more policy uncertainty, *less* implied volatility. Both
series fail an ADF test on this window, and VIXY — a short-dated VIX-futures ETF — loses
43 log-percent to roll decay over eight months. In first differences the sign flips to
positive and stays significant (β = +0.011, t = +3.33), which is both the sensible
direction and the only one a stationary regression supports. The table reports both
specifications with a stationarity verdict beside each, because the levels row is a
trap worth showing rather than deleting.

---

## Methodological details

### Covariance estimator

The covariance estimator can change the p-value by two orders of magnitude. Scores in
these daily return regressions are negatively autocorrelated, so Newey-West reduces the
standard error instead of increasing it. With n = 74, an arbitrary `maxlags=10` changes
an OLS p-value of 0.022 to 2×10⁻⁷.

The analysis uses the plug-in bandwidth `floor(4·(n/100)^(2/9))` and reports OLS, HC3,
and HAC results side by side. The false discovery rate correction uses HC3 results,
which provide the headline estimates for the contemporaneous daily regressions.

Both robust fits use the t-distribution rather than the normal. On the daily panels the
difference is immaterial, but Release 2's monthly windows run to eleven observations,
where the normal understates a two-sided p-value by enough to move a cell across an FDR
screen. Release 1's headline is unaffected: 12 of 25 pairs survive either way.

### HAC bandwidth under overlapping targets

A target built from an h-month window shares h-1 months with its own neighbour, so its
residuals are autocorrelated by construction out to h-1 whatever the sample size. The
plug-in bandwidth is a function of n alone and does not know that: on n = 389 it returns
5 for a twelve-month overlapping target, and the resulting t-statistics are 17% to 38%
too large. The monthly regressions therefore floor the Newey-West bandwidth at h-1 and
let the plug-in rule take over above it.

The same overlap sets a minimum sample. A target spanning h months carries roughly n/h
independent observations, so cells whose sample is shorter than a few multiples of h are
not estimated at all. Without that gate the eleven-month window regresses a twelve-month
overlapping volatility on EPU and reports t = −11.2 against t_OLS = −2.1, from a HAC
estimator whose bandwidth equals its sample size. That number is an artefact, and it
would otherwise have been the loudest cell in the release.

### Quoting outages

Jumps measured across a quoting outage are excluded. Two contracts stopped quoting for
9 to 13 days in April 2026. The first quote after each outage looks like a large
one-day move, but it represents a change accumulated over several weeks. Pairing that
change with one day's return would be misleading. The call to
`detect_jumps(max_stale_days=4)` removes these observations.

### SPY benchmark handling

SPY cannot serve as its own benchmark in the event study because the market model would
produce abnormal returns of exactly zero. The analysis uses a constant-mean model for
SPY instead.

---

## Running the analysis

```bash
pip install -r requirements.txt
python -m pmeq.datasets refresh    # one-time download of ETF bars; requires network access
python scripts/run_release1.py     # prediction market strand
python scripts/run_release2.py     # policy uncertainty strand
python scripts/run_release3.py     # composite index; ~2 min for the placebo
pytest tests/                      # run 49 guardrail tests
```

`run_release3.py` takes an optional placebo-draw count (`python scripts/run_release3.py
1500`). It has no effect on the reported p-values: there are only ~145 distinct circular
shifts at this sample size, so the null is enumerated exactly and any count at or above
that is identical.

Run the `refresh` command once after a fresh clone. Polymarket implied probabilities
and the EPU snapshots are committed under `data/raw/`. ETF daily bars come from a
third-party vendor and are not redistributed, so `data/raw/prices/` is empty in the
repository. After the download, the analysis runs offline and reproduces the saved
outputs from the snapshots.

If the price data are missing, each runner exits with a one-line instruction and the
price-dependent tests are skipped rather than failed, producing `26 passed, 23 skipped`.

Tables are written to `outputs/tables/*.csv`, and figures are written to
`outputs/figures/*.png`.

## Repository layout

```
src/pmeq/
  config.py       paths, contract registry with CLOB token IDs, and theme map
  datasets.py     local data loaders and live refresh layer
  stats_tools.py  HAC and HC3 regressions, stationarity, Granger tests, event study,
                  circular-shift placebo, BH-FDR, and power calculations
  release1.py     prediction market pipeline
  release2.py     policy uncertainty pipeline
  release3.py     factor construction, composite index, placebo, trend decomposition
  plots.py        figure generation
scripts/run_release1.py
scripts/run_release2.py
scripts/run_release3.py
tests/            look-ahead checks, FDR, permutation mechanics, window definitions,
                  trend control, placebo power, power arithmetic, and data sanity
data/raw/polymarket/  committed probability snapshots from the public API
data/raw/epu/         committed monthly EPU headline and categorical sub-indices
data/raw/prices/      empty until `python -m pmeq.datasets refresh` is run
outputs/          tables and figures
```

`config.py` records each contract's CLOB token ID so the exact sample can be fetched
again. `datasets.py` and `stats_tools.py` are shared across the study, and Release 4
uses the same loaders and tests.

## Data provenance

| Series | Source | In this repository |
|---|---|---|
| Implied probabilities | Polymarket CLOB `prices-history`, daily fidelity | committed |
| Contract metadata | Polymarket Gamma `/events`, `/public-search` | committed in `config.py` |
| Headline monthly EPU | policyuncertainty.com | committed |
| Categorical EPU sub-indices | FRED `EPUMONETARY`, `EPUTRADE`, `EPUSOVDEBT` | committed |
| Daily EPU | policyuncertainty.com | not retrievable here; see Release 2, result 1 |
| ETF daily bars | Yahoo Finance through `yfinance` | fetched, not redistributed |

## Caveats

- The Release 1 sample contains only 250 trading days, and the like-for-like Release 2
  window is eleven months. Release 2 quantifies what that costs.
- Prediction market bars are recorded after the equity close, so same-day results do
  not establish direction.
- Each contract has only three to nine events, and some windows overlap. The CAR tests
  therefore have little power.
- Two contracts have very low trading volume and many days with no probability change.
- The strongest full-sample relationships in Release 2 use overlapping trailing
  volatility targets. They are contemporaneous, not predictive, and are labelled as
  such in the output tables.
- The theme-matched proxy comparison rests on seven to nine monthly observations and is
  descriptive only.
- Release 3's panel rectangle is chosen from the data — both the contracts and the
  window — and neither the placebo nor anything else prices that choice. The
  sensitivity table shows a different constant selects a different panel and flips two
  signs.
- Release 3's composite is 82% one contract by volume weight, so "aggregate across
  policy domains" overstates what it measures.
- No release runs an out-of-sample test. Every result is in-sample, with the placebo and
  the trend control standing in for one.

## The remaining release

Release 4 applies the same specification to roughly 400 months of the
Baker-Bloom-Davis-Kost Economic Policy and Market Volatility tracker, where there is
enough data for the question to be answerable, and then asks what a 250-day sample
could reasonably have detected in the first place.

## License

MIT. See `LICENSE`.
