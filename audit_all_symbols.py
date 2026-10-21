"""Read-only whole-database daily OHLCV audit. Run: python audit_all_symbols.py [--mock-db]"""
import argparse
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
from src.oracle_repository import get_repository
from src.symbol_manager import SymbolManager

FIELDS = ['OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'VOLUME']

def audit_frame(frame, today=None):
    today = today or date.today()
    if frame.empty:
        return {'bars': 0, 'last_date': '', 'stale_weekdays': None, 'invalid_ohlcv': 0,
                'duplicate_dates': 0, 'future_dates': 0, 'suspicious_jumps': 0,
                'adjusted_close_missing': 0, 'status': 'NO_DATA'}
    df = frame.copy()
    dates = pd.to_datetime(df['TRADE_DATE'], errors='coerce', utc=True).dt.tz_convert('Asia/Ho_Chi_Minh').dt.date
    # Datetime strings without timezone are session dates; UTC conversion may only shift hours, not dates.
    raw_dates = pd.to_datetime(df['TRADE_DATE'], errors='coerce')
    if raw_dates.dt.tz is None:
        dates = raw_dates.dt.date
    v = df[FIELDS].apply(pd.to_numeric, errors='coerce')
    o, h, l, c, volume = [v[k] for k in FIELDS]
    bad = (~np.isfinite(v.to_numpy(dtype=float))).any(axis=1) | (o <= 0) | (h <= 0) | (l <= 0) | (c <= 0) | (volume < 0) | (volume % 1 != 0) | (h < pd.concat([o,l,c],axis=1).max(axis=1)) | (l > pd.concat([o,h,c],axis=1).min(axis=1))
    valid_dates = dates.dropna()
    last = max(valid_dates) if len(valid_dates) else None
    weekday_gap = int(np.busday_count((last + pd.Timedelta(days=1)).isoformat(),today.isoformat())) if last and last < today else 0
    ordered = pd.DataFrame({'date':dates, 'close':c}).dropna().sort_values('date')
    # Purely a flag. Corporate actions, price limits and missing sessions can explain jumps.
    jumps = ordered['close'].pct_change(fill_method=None).abs() > 0.20
    adj_missing = int(df['ADJ_CLOSE'].isna().sum()) if 'ADJ_CLOSE' in df else len(df)
    problems = int(bad.sum()) + int(dates.isna().sum()) + int(dates.duplicated().sum()) + int((dates > today).sum())
    return {'bars':len(df), 'last_date':str(last or ''), 'stale_weekdays':weekday_gap,
            'invalid_ohlcv':int(bad.sum()), 'duplicate_dates':int(dates.duplicated().sum()),
            'future_dates':int((dates > today).sum()), 'suspicious_jumps':int(jumps.sum()),
            'adjusted_close_missing':adj_missing,
            'status':'INVALID' if problems else ('REVIEW' if weekday_gap >= 2 or jumps.any() else 'OK_UNVERIFIED')}

def audit_repository(repo, output, universe=None):
    symbols = repo.get_symbols_summary()
    if universe:
        manager = SymbolManager(seed_file=universe)
        expected = manager.load_from_csv(universe)
        known = {s['symbol'] for s in symbols}
        symbols.extend({'symbol': s['symbol'], 'exchange': s['exchange']} for s in expected.to_dict('records')
                       if s['security_type'] == 'EQUITY' and s['symbol'] not in known)
    results = []
    for n, meta in enumerate(symbols, 1):
        sym = meta['symbol']
        try:
            result = audit_frame(repo.query_historical_prices(sym))
        except Exception as exc:
            result = {'status':'ERROR', 'error':str(exc)[:240]}
        results.append({'symbol':sym, 'exchange':meta.get('exchange',''), **result})
        if n % 100 == 0:
            print(f'Checked {n}/{len(symbols)} symbols', flush=True)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results, columns=['symbol','exchange','status','bars','last_date','stale_weekdays','invalid_ohlcv','duplicate_dates','future_dates','suspicious_jumps','adjusted_close_missing','error']).to_csv(path,index=False,encoding='utf-8-sig')
    print(f'Checked {len(symbols)} symbols. Report: {path}')
    print(pd.Series([r['status'] for r in results]).value_counts().to_string() if results else 'No stored symbols')
    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mock-db',action='store_true',help='Use SQLite development database instead of Oracle')
    parser.add_argument('--universe', nargs='?', const='data/vietnam_stocks.csv', default=None, help='Also report seed symbols absent from price database')
    parser.add_argument('--output',default='data/reports/all_symbols_audit.csv')
    args = parser.parse_args()
    audit_repository(get_repository(force_mock=args.mock_db),args.output,args.universe)
