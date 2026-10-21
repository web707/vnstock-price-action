# ALL-MARKET (HOSE/HNX/UPCoM) — how to run

This is a **workflow and audit upgrade**, not a guarantee of verified live prices. The bundled `data/vietnam_stocks.csv` contains 1,600 symbols; the application's current classification calls 1,579 of them equities. The CSV can be stale, contain inactive instruments or incorrect exchange labels. Yahoo Finance might not serve all of these tickers, particularly HNX and UPCoM.

## PowerShell, Windows

Extract ZIP and open PowerShell in the nested `vnstock-price-action-main` folder:

```powershell
cd "C:\Users\ADMIN\Downloads\vnstock-qta-all-market\vnstock-price-action-main"
python -m pip install -r requirements.txt
python sync_all_symbols.py
python sync_all_symbols.py --execute --mock-db --limit 10
python audit_all_symbols.py --mock-db --universe
python main.py verify --mock-db
```

The first command is a **dry-run**; the second one downloads and upserts just 10 symbols to the local SQLite DB. Look at `data/reports/coverage_details_*.csv`, `coverage_summary_*.md`, and `data/reports/all_symbols_audit.csv`.

After verifying the small batch and making a backup of `data/state/vietnam_stocks_mock.db`, run **the entire seed universe**:

```powershell
python sync_all_symbols.py --execute --mock-db --mode update
python audit_all_symbols.py --mock-db --universe
```

To backfill maximum history (slow; high number of Yahoo requests):

```powershell
python sync_all_symbols.py --execute --mock-db --mode historical
```

If you have a configured Oracle `.env`, change the flag to `--oracle`. **Never run both modes against different databases expecting them to share records.**

`--limit N` gives a small, reproducible prefix of the seed listing. No writes/downloads occur without `--execute` and an explicit database flag. The script logs and reports network `NO_DATA` / failures rather than inventing price data. Network access is required for downloading; expect rate limits and unsupported Yahoo symbols.

## What the audit means

- `NO_DATA` = symbol from CSV with no historical prices stored (not proof the stock is invalid).
- `REVIEW` = potentially stale or a large price jump; corporate actions and missing trading sessions can explain this.
- `OK_UNVERIFIED` = internal shape checks pass, **not a cross-vendor market price verification**.
- `--universe` makes missing symbols visible instead of silently auditing only tickers with prices.

**Important limitations:** weekday staleness is an approximation (no exchange holiday calendar); corporate actions are not cross-checked against an independent source. `run_pipeline.py` still defaults to a sample HPG 15m CSV and is not an all-market analysis runner. Do not interpret SQLite "Mock" as fake candles necessarily: it is a local storage mode, and can store Yahoo-downloaded candles, but all data must still be verified.
