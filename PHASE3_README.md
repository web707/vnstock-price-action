# QTA Phase 3 — Conservative data recovery (SQLite)

This is an **initial, tested recovery utility**, not a claim of verified market-wide OHLCV. The Yahoo batch report showed 397/1579 tickers with data, while the SQLite file holding ~1.2M records **stays on your Windows computer** and is not bundled in this ZIP.

## Safe setup

1. Extract this ZIP next to your prior project. **Do not delete the old directory or its database.**
2. Close your QTA dashboard/sync jobs before copying the database.
3. Copy `data/state/vietnam_stocks_mock.db` from the old project into the same path in this project, OR pass `--db "C:\\path\\to\\old\\data\\state\\vietnam_stocks_mock.db"` (recommended to work on a copy).
4. `python -m pip install -r requirements.txt`
5. `python -m pip install "vnstock>=4,<5"` (optional provider; check terms of use and rate limits).
6. Dry-run selection: `python phase3_recover.py --mode missing --limit 10`
7. Pilot write: `python phase3_recover.py --execute --mode missing --limit 10 --source VCI`
8. Review `data/reports/phase3_recovery_*.csv` and `phase3_conflicts_*.csv`, then run `python audit_all_symbols.py --mock-db`.

**DO NOT run all 1579 until the pilot source's price scale and data type have been checked.** `--price-multiplier 1000` is the default because Vnstock often quotes thousands of VND. Adjust to the actual provider/version; if no overlaps exist, independently compare sample dates/prices. Corporate-action-adjusted OHLCV versus raw OHLCV is NOT automatically reconciled. Imported `ADJ_CLOSE` is only a placeholder copy of close and `QUALITY_STATUS=UNVERIFIED_ADJ_CLOSE`; **not a certified adjusted close**. Existing prices are NEVER overwritten. Conflicts are reported but not automatically resolved. Today's still-forming candle is skipped. No assumptions that an unavailable ticker is delisted.

The bundled symbol CSV is a seed, not a verified live exchange master. Phases remaining: verify security listings, reconcile corporate actions/price basis, provider cross-checks, integrate provider selection into routine UI/pipeline, reject unverified bars from trading signals.

Reference for documented provider API: https://www.vnstocks.com/docs/vnstock/chuyen-doi/lop-tuong-thich
