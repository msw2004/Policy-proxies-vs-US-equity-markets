"""Project configuration: paths, market registry, asset registry, theme mapping.

The market registry records the *identity* of every Polymarket contract used in the
study, so that a later run can re-fetch it from the live API and reproduce the same
sample.  ``yes_token_id`` is the CLOB ERC-1155 token id of the YES outcome, which is
the argument to ``/prices-history``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"
OUT_FIG = ROOT / "outputs" / "figures"
OUT_TAB = ROOT / "outputs" / "tables"
REPORTS = ROOT / "reports"

for _p in (DATA_PROC, OUT_FIG, OUT_TAB, REPORTS):
    _p.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ policy themes
# Each theme links a family of prediction markets to (a) the categorical EPU index
# that covers the same policy domain and (b) the EMV tracker component, so that
# Releases 1, 2 and 4 are measuring the *same* policy dimension.
THEMES = {
    "monetary": {
        "label": "Monetary policy / Fed path",
        "epu_categorical": "EPUMONETARY",
        "emv_component": "EMVMONETARYPOL",
        "primary_assets": ["TLT", "XLF", "SPY"],
    },
    "growth": {
        "label": "Recession / macro outlook",
        "epu_categorical": None,          # no dedicated categorical EPU sub-index
        "emv_component": None,
        "primary_assets": ["SPY", "XLI", "XLF"],
    },
    "trade": {
        "label": "Trade policy / tariffs",
        "epu_categorical": "EPUTRADE",
        "emv_component": "EMVTRADEPOLEMV",
        "primary_assets": ["XLI", "SPY"],
    },
    "sovereign_debt": {
        "label": "Sovereign debt / default risk",
        "epu_categorical": "EPUSOVDEBT",
        "emv_component": None,
        "primary_assets": ["TLT", "SPY"],
    },
    "fiscal_shutdown": {
        "label": "Government shutdown / appropriations",
        "epu_categorical": "EPUSOVDEBT",
        "emv_component": None,
        "primary_assets": ["SPY", "TLT"],
    },
}


@dataclass(frozen=True)
class Market:
    key: str
    question: str
    theme: str
    slug: str
    yes_token_id: str
    volume_usd: float
    resolved: bool
    notes: str = ""
    assets: tuple[str, ...] = field(default=())

    @property
    def file(self) -> Path:
        return DATA_RAW / "polymarket" / f"{self.key}.csv"


# Selected by keyword search of the Gamma API over the five policy themes named in
# the brief, then ranked on ``volumeNum`` within each theme.  Volumes are USD notional
# as reported by Gamma on 2026-09-01.
MARKETS: list[Market] = [
    Market(
        key="fed_sep2026_no_change",
        question="Will there be no change in Fed interest rates after the September 2026 meeting?",
        theme="monetary",
        slug="fed-decision-in-september-762",
        yes_token_id="5615282760875985231868508008056959876238536896643315063916840237042205273721",
        volume_usd=16_181_391.81,
        resolved=False,
        notes="Highest-volume 'no change' leg of the Sept-2026 FOMC event.",
        assets=("TLT", "XLF", "SPY", "XLI", "VIXY"),
    ),
    Market(
        key="fed_sep2026_hike25",
        question="Will the Fed increase interest rates by 25 bps after the September 2026 meeting?",
        theme="monetary",
        slug="fed-decision-in-september-762",
        yes_token_id="63842529068710005716169325380315470359047749786610778647370693404952498013178",
        volume_usd=14_337_500.65,
        resolved=False,
        notes="Hike leg; the 2026 regime prices meaningful tightening risk.",
        assets=("TLT", "XLF", "SPY", "XLI", "VIXY"),
    ),
    Market(
        key="fed_hike_2026",
        question="Fed rate hike in 2026?",
        theme="monetary",
        slug="fed-rate-hike-in-2026",
        yes_token_id="75028752776148090296091099469912621384650554615761384992997579209329182670110",
        volume_usd=8_206_363.56,
        resolved=False,
        notes="Year-horizon hike risk; longest monetary-policy history in the sample.",
        assets=("TLT", "XLF", "SPY", "XLI", "VIXY"),
    ),
    Market(
        key="us_recession_2026",
        question="US recession by end of 2026?",
        theme="growth",
        slug="us-recession-by-end-of-2026",
        yes_token_id="100379208559626151022751801118534484742123694725746262280150222742563282755057",
        volume_usd=1_717_659.17,
        resolved=False,
        assets=("SPY", "XLI", "XLF", "TLT", "VIXY"),
    ),
    Market(
        key="korea_trade_deal_2027",
        question='U.S. agrees to a new trade deal with "South Korea" before 2027?',
        theme="trade",
        slug="which-countries-will-trump-make-new-trade-deals-with-before-2027-921",
        yes_token_id="37480061466688501596287441287412956096859286916194283564307593928320601178597",
        volume_usd=59_656.99,
        resolved=False,
        notes="Thin market; retained because the brief names the US-Korea trade case.",
        assets=("XLI", "SPY"),
    ),
    Market(
        key="us_debt_default_2027",
        question="US defaults on debt by 2027?",
        theme="sovereign_debt",
        slug="us-defaults-on-debt-by-2027",
        yes_token_id="114437641958570534735982376736844126362165493704104291576224648286615737546344",
        volume_usd=16_228.31,
        resolved=False,
        notes="Thin tail-risk market; probabilities live in the 2-8% range.",
        assets=("TLT", "SPY", "VIXY"),
    ),
    Market(
        key="gov_shutdown_2025",
        question="US government shutdown in 2025?",
        theme="fiscal_shutdown",
        slug="us-government-shutdown-in-2025",
        yes_token_id="72694124641274932882200626543149578267721455356147469547452575814170241772944",
        volume_usd=3_512_314.57,
        resolved=True,
        notes=(
            "Resolved YES on 2025-10-01. Only ~20 trading days overlap the daily price "
            "window, so it is used for the event study but not for rolling correlation."
        ),
        assets=("SPY", "TLT", "XLF", "VIXY"),
    ),
]

MARKETS_BY_KEY = {m.key: m for m in MARKETS}

# ------------------------------------------------------------------------- assets
ASSETS = {
    "SPY": "S&P 500 ETF - broad US equity",
    "TLT": "20+ Year Treasury ETF - long-duration rates",
    "XLF": "Financials sector ETF - rate/credit sensitive",
    "XLI": "Industrials sector ETF - trade/tariff sensitive",
    "VIXY": "Short-term VIX futures ETF - implied-volatility proxy",
}
BENCHMARK = "SPY"

# --------------------------------------------------------------------- estimation
ROLL_WINDOW = 21          # trading days, per the brief
EVENT_WINDOW = (-5, 5)    # CAR window around a probability jump
ESTIMATION_WINDOW = 60    # trading days used to fit the market model
JUMP_SIGMA = 2.0          # |dp| threshold in standard deviations
JUMP_MIN_PP = 0.03        # ...and an absolute floor of 3 percentage points
MAX_GRANGER_LAG = 5
HAC_LAGS_DAILY = "auto"      # Newey-West plug-in, see stats_tools.nw_lags
HAC_LAGS_MONTHLY = "auto"
N_PLACEBO = 1500
RANDOM_SEED = 20260901
