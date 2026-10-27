# QTA Phase 3.1 - SQLite safety patch

- Vnstock v4 quote imports from `vnstock.api.quote` (tested at import interface; external network not tested here).
- New VCI/KBS rows set `ADJ_CLOSE = NULL` and `QUALITY_STATUS = UNVERIFIED_ADJ_CLOSE` until independently validated. No rewriting of existing SQLite records is performed by this package.
- Web daily-price boundary excludes the current Vietnam-calendar-day candle from data used downstream. This is a conservative guard and may omit a completed session until the next day.
- `phase3_recover.py` remains dry-run by default; `--execute` makes a SQLite backup and INSERT OR IGNORE operations. Always use a TEST copy of the DB.
- Existing imported rows with misleading `ADJ_CLOSE` or `QUALITY_STATUS` are NOT retroactively altered. The protection applies to new Phase 3.1 imports and the web daily-data boundary, not to every independent pipeline consumer.

## Windows commands

```powershell
cd "C:\Users\ADMIN\Downloads\vnstock-qta-phase31-sqlite\vnstock-price-action-main"
python -m pip install -r requirements.txt
python -m pip install --extra-index-url https://vnstocks.com/api/simple "vnstock>=4,<5"
python -m pytest -q tests/test_phase3_recover.py tests/test_phase31_daily_guard.py
python phase3_recover.py --mode missing --limit 10 --db "C:\Users\ADMIN\Downloads\vnstock-qta-phase3-sqlite (1)\vnstock-price-action-main\data\state\qta_phase3_test.db"
```

The last command is dry-run only. When ready, use a fresh disposable copy of the DB before adding `--execute`.
