# Yahoo Finance snapshot (to 29 May 2026)

CSV files saved by the Phase 2 pipeline: `nifty.csv` and `vix.csv` are the raw
downloads, `market_data.csv` is the result of the old inner join (17 days missing).

They are **test fixtures only** (`ml/tests/test_real_history.py`); the pipeline no
longer reads or writes this folder. Source: Yahoo Finance via yfinance, for
personal/educational use under Yahoo's terms.
