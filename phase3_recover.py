"""Phase 3: conservative VN-stock recovery into the existing SQLite DB.

Dry-run by default. On execute, backs up SQLite, inserts ONLY missing bars,
never replaces an existing bar; source disagreements are exported for review.
"""
import argparse
import csv
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from src.config import settings
from src.oracle_repository import MockSqliteRepository

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
REPORTS = Path('data/reports')
FIELDS = ['symbol','exchange','source','status','fetched','inserted','overlap','conflicts','skipped_forming','error']


def load_universe(path):
    from src.symbol_manager import SymbolManager
    manager = SymbolManager(seed_file=str(path))
    manager.load_from_csv(str(path))
    return manager.filter_symbols(exchanges=['HOSE','HNX','UPCOM'], security_types=['EQUITY'])


def candidates(universe, connection, mode):
    known = {r[0]: r[1] for r in connection.execute('SELECT SYMBOL, MAX(TRADE_DATE) FROM STOCK_PRICES GROUP BY SYMBOL')}
    today = datetime.now(TZ).date()
    if mode == 'missing':
        return [s for s in universe if not known.get(s['symbol'])]
    if mode == 'stale':
        return [s for s in universe if not known.get(s['symbol']) or (today - datetime.fromisoformat(str(known[s['symbol']])[:10]).date()).days > 5]
    return universe


def normalize_vnstock(df, price_multiplier=1000):
    """Normalize vnstock historical dataframe to VND OHLCV; avoid fake adjusted closes."""
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    data.columns = [str(c).strip().lower() for c in data.columns]
    date_col = next((col for col in ('time','date','trading_date') if col in data.columns), None)
    if not date_col or any(col not in data for col in ('open','high','low','close','volume')):
        raise ValueError(f'Unexpected source schema: {list(data.columns)}')
    data['trade_date'] = pd.to_datetime(data[date_col], errors='coerce').dt.date
    for col in ('open','high','low','close','volume'):
        data[col] = pd.to_numeric(data[col], errors='coerce')
    for col in ('open','high','low','close'):
        data[col] *= price_multiplier
    data = data.dropna(subset=['trade_date','open','high','low','close','volume'])
    data = data[(data[['open','high','low','close']] > 0).all(axis=1) & (data['volume'] >= 0)]
    data = data[(data.high >= data[['open','low','close']].max(axis=1)) & (data.low <= data[['open','high','close']].min(axis=1))]
    return data.sort_values('trade_date').drop_duplicates('trade_date', keep='last')


def fetch_vnstock(symbol, start, end, source='VCI'):
    try:
        from vnstock.api.quote import Quote
    except ImportError as ex:
        raise RuntimeError('Install optional package: python -m pip install --extra-index-url https://vnstocks.com/api/simple "vnstock>=4,<5"') from ex
    return Quote(symbol=symbol, source=source).history(start=start, end=end, interval='d')


def is_closed(trade_date, now):
    # Conservative: no current-day candles until next calendar day; holiday calendar not assumed.
    return trade_date < now.date()


def inspect_symbol(conn, symbol, exchange, source, df, now, tolerance=0.03):
    existing = {str(r[0])[:10]: float(r[1]) for r in conn.execute('SELECT TRADE_DATE, CLOSE_PRICE FROM STOCK_PRICES WHERE SYMBOL=?', (symbol,))}
    insert_rows, disagreements = [], []
    skipped_forming = overlaps = 0
    for r in df.itertuples():
        date_str = r.trade_date.isoformat()
        if not is_closed(r.trade_date, now):
            skipped_forming += 1
            continue
        if date_str in existing:
            overlaps += 1
            if existing[date_str] > 0 and abs(float(r.close) / existing[date_str] - 1) > tolerance:
                disagreements.append({'symbol':symbol,'date':date_str,'source':source,'existing_close':existing[date_str], 'provider_close':float(r.close),'reason':'CLOSE_DIFFERENCE_REVIEW_PRICE_BASIS'})
            continue
        insert_rows.append((symbol,date_str,float(r.open),float(r.high),float(r.low),float(r.close),None,int(r.volume),'UNVERIFIED_ADJ_CLOSE',f'vnstock_{source.lower()}',now.isoformat()))
    return insert_rows, disagreements, overlaps, skipped_forming


def execute(argv=None, fetcher=fetch_vnstock, clock=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--mode', choices=('missing','stale','all'), default='missing')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--source', choices=('VCI','KBS'), default='VCI')
    parser.add_argument('--start', default='2015-01-01')
    parser.add_argument('--end', default=None)
    parser.add_argument('--price-multiplier', type=float, default=1000.0, help='VNStock often returns prices in 1000 VND; verify with overlap first')
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--db', default=str(settings.state_dir / 'vietnam_stocks_mock.db'))
    parser.add_argument('--universe', default='data/vietnam_stocks.csv')
    args = parser.parse_args(argv)
    if args.limit < 1 or args.price_multiplier <= 0 or args.delay < 0:
        parser.error('limit, multiplier must be positive; delay nonnegative')
    now = clock or datetime.now(TZ)
    db = Path(args.db)
    if not db.exists():
        parser.error(f'Database not found: {db}. Restore your previous DB; refusing to create an empty replacement.')
    with sqlite3.connect(db) as conn:
        selected = candidates(load_universe(args.universe), conn, args.mode)[:args.limit]
    print(f'Phase3 {args.mode}: {len(selected)} selected; SQLite={db}; execute={args.execute}')
    print('Sample:', ', '.join(x['symbol'] for x in selected[:15]))
    if not args.execute:
        print('DRY RUN: No network requests or database writes. Add --execute to fetch and stage missing bars.')
        return 0
    REPORTS.mkdir(parents=True, exist_ok=True)
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    backup = db.with_suffix(db.suffix + f'.phase3_{timestamp}.bak')
    # Native online SQLite backup (safe even if another process has the database open).
    with sqlite3.connect(db) as source_conn, sqlite3.connect(backup) as backup_conn:
        source_conn.backup(backup_conn)
    print(f'SQLite backup created: {backup}')
    end = args.end or (now.date() + timedelta(days=1)).isoformat()
    summary, conflicts = [], []
    for idx, item in enumerate(selected, 1):
        sym, exch = item['symbol'], item.get('exchange','UNKNOWN')
        entry = dict(symbol=sym,exchange=exch,source=args.source,status='FAILED',fetched=0,inserted=0,overlap=0,conflicts=0,skipped_forming=0,error='')
        try:
            raw = fetcher(sym,args.start,end,args.source)
            clean = normalize_vnstock(raw,args.price_multiplier)
            entry['fetched'] = len(clean)
            if clean.empty:
                entry['status']='NO_DATA'
            else:
                with sqlite3.connect(db) as conn:
                    inserts, diffs, overlaps, forming = inspect_symbol(conn,sym,exch,args.source,clean,now)
                    entry.update(overlap=overlaps,conflicts=len(diffs),skipped_forming=forming)
                    conflicts.extend(diffs)
                    # Atomic insert-only; NEVER override a previously stored bar.
                    if inserts:
                        conn.executemany('''INSERT OR IGNORE INTO STOCK_PRICES
                          (SYMBOL,TRADE_DATE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,ADJ_CLOSE,VOLUME,QUALITY_STATUS,SOURCE,FETCHED_AT)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''', inserts)
                        entry['inserted'] = conn.execute('SELECT changes()').fetchone()[0] if len(inserts)==1 else conn.total_changes
                    entry['status']='REVIEW' if diffs else 'INSERTED' if inserts else 'UNCHANGED'
        except Exception as exc:
            entry['error']=f'{type(exc).__name__}: {exc}'[:400]
        summary.append(entry)
        print(f"[{idx}/{len(selected)}] {sym} {entry['status']} +{entry['inserted']} conflicts={entry['conflicts']} {entry['error']}", flush=True)
        if args.delay:
            time.sleep(args.delay)
    for filename, rows, columns in ((f'phase3_recovery_{timestamp}.csv',summary,FIELDS), (f'phase3_conflicts_{timestamp}.csv',conflicts,['symbol','date','source','existing_close','provider_close','reason'])):
        path = REPORTS / filename
        with open(path,'w',newline='',encoding='utf-8-sig') as out:
            writer=csv.DictWriter(out,fieldnames=columns); writer.writeheader();writer.writerows(rows)
        print('Report:',path)
    return 0


if __name__ == '__main__':
    raise SystemExit(execute())
