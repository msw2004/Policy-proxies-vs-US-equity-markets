# ETF price snapshots

Deliberately empty. Daily bars for SPY, TLT, XLF, XLI and VIXY are third-party vendor
data, so they are not redistributed here. Fetch them once:

```bash
python -m pmeq.datasets refresh
```

That writes `SPY.csv`, `TLT.csv`, `XLF.csv`, `XLI.csv` and `VIXY.csv` into this
directory with columns `date,open,high,low,close,adj_close,volume`, after which the
whole analysis runs offline.

The Polymarket implied-probability snapshots under `../polymarket/` *are* committed —
they come from a public API.
