"""Explicit, resumable all-symbol synchronization from the bundled CSV universe.

Default is dry-run. The CSV is a seed, NOT a verified live exchange listing.
Use --execute --mock-db for local SQLite or --execute --oracle for configured Oracle.
"""
import argparse
import sys
from pathlib import Path
from src.symbol_manager import SymbolManager
from src.oracle_repository import get_repository


def plan(csv=None, exchanges=None, limit=None):
    manager = SymbolManager(seed_file=csv)
    manager.load_from_csv(csv)
    return manager.filter_symbols(exchanges=exchanges, security_types=['EQUITY'], limit=limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', default=None, help='Seed universe CSV (not a verified live listing)')
    parser.add_argument('--exchange', default='HOSE,HNX,UPCOM')
    parser.add_argument('--limit', type=int, default=None, help='Try a small batch first')
    parser.add_argument('--execute', action='store_true', help='Explicitly write to database and download market data')
    dest = parser.add_mutually_exclusive_group()
    dest.add_argument('--mock-db', action='store_true', help='Local SQLite test database')
    dest.add_argument('--oracle', action='store_true', help='Configured Oracle')
    parser.add_argument('--mode', choices=['update', 'historical'], default='update')
    parser.add_argument('--days-back', type=int, default=None)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be positive')
    if args.days_back is not None and args.days_back <= 0:
        parser.error('--days-back must be positive')
    exchanges = [x.strip().upper() for x in args.exchange.split(',') if x.strip()]
    if set(exchanges) - {'HOSE','HNX','UPCOM'}:
        parser.error('Supported exchanges: HOSE,HNX,UPCOM')
    symbols = plan(args.csv, exchanges, args.limit)
    print(f'Universe seed: {args.csv or "data/vietnam_stocks.csv"}; selected equity symbols: {len(symbols)}')
    print('WARNING: seed may contain stale/delisted symbols; Yahoo may lack coverage.')
    if not symbols:
        print('No matching symbols.'); return 1
    if not args.execute:
        print('DRY RUN: no network or database writes. Preview:', ', '.join(s['symbol'] for s in symbols[:15]))
        print('To run: python sync_all_symbols.py --execute --mock-db --limit 10')
        return 0
    if not args.mock_db and not args.oracle:
        parser.error('Select --mock-db or --oracle explicitly for writes')
    repo = get_repository(force_mock=args.mock_db)
    ok, msg = repo.check_connection()
    if not ok:
        print(f'Database not available: {msg}', file=sys.stderr); return 2
    repo.upsert_symbols(symbols)
    print(f'Registered {len(symbols)} symbols; downloading data sequentially...')
    if args.mode == 'historical':
        from src.historical_importer import HistoricalImporter
        reporter = HistoricalImporter(repository=repo).import_symbols(symbols_meta=symbols)
    else:
        from src.incremental_updater import IncrementalUpdater
        reporter = IncrementalUpdater(repository=repo).update_symbols(symbols_meta=symbols, force_days_back=args.days_back)
    if reporter is None:
        print('Pipeline finished without a reporter; inspect logs'); return 3
    print(f'Reports: data/reports/coverage_details_* and coverage_summary_* (written by importer/updater)')
    result = reporter.generate_summary()
    print(f"Processed: {result['total_input_symbols']}; success: {result['successful_symbols']}; partial: {result['partial_symbols']}; no_data: {result['no_data_symbols']}; failed: {result['failed_symbols']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
