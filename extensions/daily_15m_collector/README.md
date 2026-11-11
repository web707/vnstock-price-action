# Module A — VN30 15-minute collector

On Windows, create the root `.venv` and install the dependencies from the root README. For a manual collection, run:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m extensions.daily_15m_collector.collector --help
.\.venv\Scripts\python.exe -X utf8 extensions/daily_15m_collector/collect_vn30_yahoo.py --fallback-59
```

The VN30 adapter reads `config.vn30.2026-07.json`, tries each `.VN` symbol independently and writes an append-only SQLite database in this module's `data/` directory. It records each ticker's outcome in `logs/fetch_runs.jsonl`. The composite candle key is ticker, timeframe and timestamp. Existing rows are preserved when Yahoo revises values.

For after-close scheduling use [the Windows guide](../../docs/WINDOWS_VN30_COLLECTOR.md). The original five-symbol collector remains available via `collector.py --config config.json`.

The requested Yahoo window is `60d`. A `59d` retry is available for failed requests. Coverage, missing slots and source release timing vary. Preserve `fetched_at` and treat timestamp labels as unverified for historical replay.
