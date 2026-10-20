# Source audit — Git snapshot vs previous fixed snapshot

Git snapshot (file 1) remains the base. Old `main.py` and `inspect_swings.py` both silently fell back from intraday API to daily SQLite. The previous fixed snapshot (file 2) handled `inspect_swings.py` API errors but did not forbid `--source db --timeframe 15m` and did not patch `main.py`.

Changes in this edition: reject explicit intraday SQLite selection; raise API failure clearly without fallback; verify median 15m spacing in both legacy entrypoints and Layer 1 detector; preserve SQLite for explicit `1d`; timezone conversion in the modular detector; lazy API import in the modular runner. No ATR, ZigZag or swing threshold changes.

Assumptions: local SQLite `STOCK_PRICES` is daily-only; `15m` requires API or a genuine 15m CSV in modular pipeline; 14–16min is timestamp-cadence validation tolerance (not a swing threshold); legacy `MarketStructureBuilder` direct-call 1d behavior is preserved to avoid changing independent daily-data tests. For source parity on the original screenshots, the exact source dataset or command line is still required.
