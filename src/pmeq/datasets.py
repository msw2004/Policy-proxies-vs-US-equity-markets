"""Data access layer.

Two backends sit behind one interface:

* ``local``  - read the CSV snapshots committed under ``data/raw``.  This is what runs
  in a sandbox with no outbound network, and it is what the published results use.
* ``live``   - hit the canonical sources (Polymarket Gamma/CLOB, Yahoo via yfinance,
  policyuncertainty.com, FRED).  Use this to refresh the snapshots on a machine with
  internet access:  ``python -m pmeq.datasets refresh``.

Every loader returns a tidy, timezone-naive, ascending pandas object so the analysis
code never has to think about provenance.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_RAW, MARKETS, MARKETS_BY_KEY, Market

# --------------------------------------------------------------------------------
# Live endpoints (documented so the snapshots can always be regenerated)
# --------------------------------------------------------------------------------
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
EPU_MONTHLY_URL = "https://www.policyuncertainty.com/media/US_Policy_Uncertainty_Data.csv"
EPU_DAILY_URL = "https://www.policyuncertainty.com/media/All_Daily_Policy_Data.csv"
FRED_TXT = "https://fred.stlouisfed.org/data/{series}.txt"
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&page&_format=csv"
)

# US Eastern is the reference clock.  Measured on this snapshot, the CLOB's daily bars
# are stamped at 00:00 UTC, i.e. 19:00 ET under EST and 20:00 ET under EDT - three to
# four hours AFTER the 16:00 ET equity close.  So the bar dated D already contains
# day D's close, and using it to predict D+1 involves no look-ahead.  The flip side is
# that a same-day correlation between dp_D and the return on D cannot establish
# direction: the probability had the whole afternoon to react to the tape.
MARKET_TZ = "America/New_York"


# ================================================================= local loaders
class PriceDataMissing(FileNotFoundError):
    """Raised when the ETF snapshots have not been fetched yet."""


def load_prices(ticker: str) -> pd.DataFrame:
    """Daily OHLC/adjusted-close bars for one ETF, ascending by date.

    Price bars are third-party vendor data and are deliberately not committed to
    this repository; ``data/raw/prices/`` ships empty.  Populate it once with
    ``python -m pmeq.datasets refresh`` (needs network access) and everything
    afterwards runs offline.
    """
    path = DATA_RAW / "prices" / f"{ticker}.csv"
    if not path.exists():
        raise PriceDataMissing(
            f"No price snapshot for {ticker} at {path}.\n"
            "ETF bars are vendor data and are not redistributed with this repo.\n"
            "Fetch them once with:  python -m pmeq.datasets refresh"
        )
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    df.index.name = "date"
    return df


def load_price_panel(tickers: list[str] | None = None) -> pd.DataFrame:
    """Wide panel of adjusted closes, inner-joined on common trading days."""
    tickers = tickers or ["SPY", "TLT", "XLF", "XLI", "VIXY"]
    cols = {t: load_prices(t)["adj_close"] for t in tickers}
    return pd.DataFrame(cols).dropna(how="any").sort_index()


def load_returns(tickers: list[str] | None = None) -> pd.DataFrame:
    """Daily log returns of the adjusted-close panel."""
    px = load_price_panel(tickers)
    return np.log(px).diff().dropna(how="all")


def load_spy_monthly() -> pd.DataFrame:
    """Monthly SPY closes (1993-02 onwards) indexed by month-end period."""
    path = DATA_RAW / "prices" / "SPY_monthly.csv"
    df = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    df["month"] = df["date"].dt.to_period("M")
    df = df.set_index("month")[["close", "adj_close"]]
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_polymarket(key: str, tz: str = MARKET_TZ) -> pd.Series:
    """Daily implied probability for one market, indexed by US trading date.

    The CLOB returns one bar per ``fidelity`` window stamped in Unix seconds (00:00
    UTC for daily bars, i.e. 19:00/20:00 ET - after the US close).  We convert to US
    Eastern, take the last bar per calendar date, and return a float series named
    after the market key.
    """
    m = MARKETS_BY_KEY[key]
    df = pd.read_csv(m.file)
    ts = pd.to_datetime(df["t"], unit="s", utc=True).dt.tz_convert(tz)
    out = pd.Series(df["p"].astype(float).values, index=ts.dt.normalize().dt.tz_localize(None))
    out = out.groupby(level=0).last().sort_index()
    out.name = key
    return out


def load_polymarket_panel(keys: list[str] | None = None) -> pd.DataFrame:
    keys = keys or [m.key for m in MARKETS]
    return pd.DataFrame({k: load_polymarket(k) for k in keys}).sort_index()


def load_epu_monthly() -> pd.Series:
    """Headline US news-based EPU index, monthly, 1985-01 onwards."""
    df = pd.read_csv(DATA_RAW / "epu" / "us_epu_monthly.csv")
    s = pd.Series(df["epu_news"].values, index=pd.PeriodIndex(df["month"], freq="M"))
    s.name = "EPU"
    return s.sort_index()


def load_categorical_epu(series: str) -> pd.Series:
    df = pd.read_csv(DATA_RAW / "epu" / f"{series}.csv")
    s = pd.Series(df["value"].values, index=pd.PeriodIndex(df["month"], freq="M"))
    s.name = series
    return s.sort_index()


def load_emv(series: str = "EMVOVERALLEMV") -> pd.Series:
    df = pd.read_csv(DATA_RAW / "emv" / f"{series}.csv")
    s = pd.Series(df["value"].values, index=pd.PeriodIndex(df["month"], freq="M"))
    s.name = series
    return s.sort_index()


def load_epu_daily() -> pd.Series | None:
    """Daily US EPU with the 7-day smoothing applied downstream.

    Returns ``None`` when the snapshot is absent.  The sandbox that produced the
    published results could not retrieve this file (the fetch layer truncates the
    15k-row CSV at ~2.9k lines, i.e. mid-1992), so Release 2 falls back to the
    monthly indices and says so.  On a networked machine ``refresh()`` fills it in.
    """
    path = DATA_RAW / "epu" / "us_epu_daily.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    s = df["daily_policy_index"].astype(float)
    s.name = "EPU_daily"
    return s


def load_treasury_yields() -> pd.DataFrame:
    """Daily constant-maturity Treasury yields (percent) from Treasury.gov."""
    frames = []
    for path in sorted((DATA_RAW / "rates").glob("treasury_yields_*.csv")):
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
        frames.append(df.drop(columns=["Date"]).set_index("date"))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames).sort_index()
    out.columns = [c.strip() for c in out.columns]
    return out


# ================================================================ derived series
def realized_vol(returns: pd.Series, window: int = 21, annualize: bool = True) -> pd.Series:
    """Backward-looking realized volatility from daily log returns."""
    rv = returns.rolling(window).std()
    return rv * np.sqrt(252) if annualize else rv


def forward_realized_vol(returns: pd.Series, horizon: int = 5, annualize: bool = True) -> pd.Series:
    """Volatility realised over the *next* ``horizon`` days (the forecast target).

    ``rolling(h).std().shift(-h)`` evaluated at t is the standard deviation of
    returns on t+1..t+h, so a regression of this on information dated t contains no
    look-ahead.
    """
    fut = returns.rolling(horizon).std().shift(-horizon)
    return fut * np.sqrt(252) if annualize else fut


def to_month(idx: pd.DatetimeIndex) -> pd.PeriodIndex:
    return pd.PeriodIndex(idx, freq="M")


def data_inventory() -> pd.DataFrame:
    """One row per snapshot file: rows, first and last observation."""
    rows = []
    for path in sorted(DATA_RAW.rglob("*.csv")):
        df = pd.read_csv(path)
        first_col = df.columns[0]
        rows.append(
            {
                "file": str(path.relative_to(DATA_RAW)),
                "rows": len(df),
                "first": str(df[first_col].iloc[0]),
                "last": str(df[first_col].iloc[-1]),
            }
        )
    return pd.DataFrame(rows)


# ==================================================================== live layer
def _requests():
    import requests  # imported lazily so the local backend needs no network stack

    return requests


def fetch_polymarket_history(token_id: str, fidelity: int = 1440) -> pd.DataFrame:
    r = _requests().get(
        f"{CLOB}/prices-history",
        params={"market": token_id, "interval": "max", "fidelity": fidelity},
        timeout=30,
    )
    r.raise_for_status()
    return pd.DataFrame(r.json()["history"])


def search_markets(query: str, limit: int = 20) -> pd.DataFrame:
    """Keyword search of Gamma, ranked by traded volume - the Release 1 selector."""
    r = _requests().get(
        f"{GAMMA}/public-search", params={"q": query, "limit_per_type": limit}, timeout=30
    )
    r.raise_for_status()
    rows = []
    for ev in r.json().get("events", []):
        for mk in ev.get("markets", []) or []:
            rows.append(
                {
                    "event_slug": ev.get("slug"),
                    "question": mk.get("question"),
                    "group_item": mk.get("groupItemTitle"),
                    "volume_usd": mk.get("volumeNum"),
                    "start": mk.get("startDate"),
                    "end": mk.get("endDate"),
                    "closed": mk.get("closed"),
                    "clob_token_ids": mk.get("clobTokenIds"),
                }
            )
    out = pd.DataFrame(rows)
    return out.sort_values("volume_usd", ascending=False) if len(out) else out


def fetch_prices_yf(ticker: str, start: str = "2015-01-01") -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(ticker, start=start, auto_adjust=False, progress=False)
    df = df.rename(
        columns={"Open": "open", "High": "high", "Low": "low",
                 "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}
    )
    df.index.name = "date"
    return df


def fetch_epu_daily_live() -> pd.Series:
    txt = _requests().get(EPU_DAILY_URL, timeout=60).text
    df = pd.read_csv(io.StringIO(txt)).dropna(subset=["daily_policy_index"])
    df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=df.day))
    return df.set_index("date")["daily_policy_index"].sort_index()


def fetch_fred_series(series: str) -> pd.Series:
    """Parse a FRED table-data page into a series (works without an API key)."""
    txt = _requests().get(FRED_TXT.format(series=series), timeout=60).text
    rows = []
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0][:4].isdigit() and "-" in parts[0]:
            try:
                rows.append((parts[0], float(parts[1])))
            except ValueError:
                continue
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.Series([r[1] for r in rows], index=idx, name=series).sort_index()


def refresh(outdir: Path = DATA_RAW, prices_only: bool = False) -> None:
    """Fetch what Release 1 needs from the canonical sources. Requires network.

    On a fresh clone only the ETF bars are actually missing - the Polymarket
    snapshots are committed - so ``refresh(prices_only=True)`` is the cheap path.
    The EPU and EMV loaders below are used by Releases 2-4 and are not fetched here.
    """
    if not prices_only:
        (outdir / "polymarket").mkdir(parents=True, exist_ok=True)
        for m in MARKETS:
            hist = fetch_polymarket_history(m.yes_token_id)
            hist.to_csv(m.file, index=False)
            print(f"  polymarket/{m.key}: {len(hist)} bars")

    (outdir / "prices").mkdir(parents=True, exist_ok=True)
    for t in ["SPY", "TLT", "XLF", "XLI", "VIXY"]:
        px = fetch_prices_yf(t)
        px.to_csv(outdir / "prices" / f"{t}.csv")
        print(f"  prices/{t}: {len(px)} bars")
    print("refresh complete")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        refresh(prices_only="--prices-only" in sys.argv)
    else:
        print(data_inventory().to_string(index=False))
