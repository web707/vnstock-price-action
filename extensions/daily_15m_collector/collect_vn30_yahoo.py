"""Fetch Yahoo 15m history into the independent collector database."""
import argparse
import csv
import json
import msvcrt
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from collections import Counter

import yfinance as yf

from collector import TZ, DDL, normalize_time, validate

FIELDS = ('open', 'high', 'low', 'close', 'volume')
SOURCE = 'YAHOO_FINANCE_YFINANCE'
yf.config.debug.hide_exceptions = False


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def rejection(row):
    import math
    values = dict(zip(FIELDS, (float(row[field]) for field in FIELDS)))
    issues = [f'{key}=nonfinite' for key, value in values.items() if not math.isfinite(value)]
    issues += [f'{key}<=0' for key in FIELDS[:4] if values[key] <= 0]
    if values['volume'] < 0:
        issues.append('volume<0')
    if values['high'] < max(values['open'], values['close'], values['low']):
        issues.append('high<max(open,close,low)')
    if values['low'] > min(values['open'], values['close'], values['high']):
        issues.append('low>min(open,close,high)')
    return issues


def fetch(ticker, days, fallback):
    requests = []
    for period in [f'{days}d', *(['59d'] if days == 60 and fallback else [])]:
        try:
            instrument = yf.Ticker(f'{ticker}.VN')
            frame = instrument.history(
                period=period, interval='15m', auto_adjust=False, keepna=True,
                actions=False, timeout=15,
            )
            if frame.empty:
                raise ValueError('EMPTY_RESPONSE')
            return frame, period, requests
        except Exception as exc:
            requests.append(dict(period=period, code=type(exc).__name__, detail=str(exc)))
    return None, '', requests


def scheduled_session(base, log):
    now = datetime.now(TZ)
    today = now.date()
    closed_dates = json.loads((base / 'hose_holidays.json').read_text(encoding='utf-8'))['closed_dates']
    if str(today.year) not in closed_dates:
        result = dict(status='ERROR', reason='HOSE_CALENDAR_YEAR_MISSING', date=str(today))
        code = 4
    elif today.weekday() >= 5 or str(today) in closed_dates[str(today.year)]:
        result = dict(status='SKIPPED', reason='HOSE_NON_TRADING_DAY', date=str(today))
        code = 0
    else:
        session = today
        if now.time() < time(15, 15):
            session -= timedelta(days=1)
            while session.weekday() >= 5 or str(session) in closed_dates.get(str(session.year), []):
                session -= timedelta(days=1)
        return session.isoformat(), None
    line = json.dumps(dict(recorded_at=timestamp(), **result))
    with log.open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')
    print(line, flush=True)
    return None, code


def run(args):
    cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
    base = args.config.resolve().parent
    db, log = (base / cfg[key] for key in ('database', 'log'))
    db.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    days = args.days if args.days is not None else cfg['lookback_days']
    if not 1 <= days <= 60:
        raise ValueError('days must be in [1, 60]')
    expected_session = None
    if args.scheduled:
        expected_session, exit_code = scheduled_session(base, log)
        if exit_code is not None:
            return exit_code
    summary = []
    with closing(sqlite3.connect(db)) as connection, log.open('a', encoding='utf-8') as log_stream:
        connection.executescript(DDL)
        connection.execute('''CREATE TABLE IF NOT EXISTS yahoo_import_metadata (
            ticker TEXT NOT NULL, timeframe TEXT NOT NULL, candle_time TEXT NOT NULL,
            import_run_id INTEGER NOT NULL REFERENCES fetch_runs(run_id),
            source_timezone TEXT NOT NULL, timestamp_label TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            PRIMARY KEY(ticker,timeframe,candle_time),
            FOREIGN KEY(ticker,timeframe,candle_time) REFERENCES candles_15m(ticker,timeframe,candle_time)
        )''')
        connection.execute('PRAGMA foreign_keys=ON')
        for ticker in cfg['tickers']:
            started = timestamp()
            frame, period, errors = fetch(ticker, days, args.fallback_59)
            fetched_at = timestamp()
            counts = dict(new=0, duplicate=0, changed_duplicate=0, invalid=0)
            valid_times = []
            rejected = []
            rejected_counts = Counter()
            raw = []
            source_timezone = str(frame.index.tz) if frame is not None else ''
            if frame is not None:
                for when, values in frame.iterrows():
                    original = {field: float(values[field.title()]) for field in FIELDS}
                    record = dict(ticker=ticker, candle_time=when.to_pydatetime(), source=SOURCE, **original)
                    try:
                        row = validate(record)
                        if normalize_time(record['candle_time']) > datetime.now(TZ):
                            raise ValueError('FUTURE_TIMESTAMP')
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        issues = rejection(original)
                        rejected_counts.update(issues or [str(exc)])
                        if args.evidence or len(rejected) < 5:
                            rejected.append(dict(time=when.isoformat(), error=str(exc),
                                                 issues=issues, raw={k: repr(v) for k,v in original.items()}))
                        counts['invalid'] += 1
                        continue
                    if expected_session and row[2][:10] > expected_session:
                        continue
                    raw.append((*row[:-1], fetched_at))
                    valid_times.append(row[2])
            with connection:
                run_id = connection.execute(
                    'INSERT INTO fetch_runs(started_at,source,inserted,duplicate,invalid,errors) VALUES (?,?,?,?,?,?)',
                    (started,SOURCE,0,0,counts['invalid'],json.dumps(dict(ticker=ticker,errors=errors,rejected=rejected))),
                ).lastrowid
                for row in raw:
                    prior = connection.execute(
                        'SELECT open,high,low,close,volume FROM candles_15m WHERE ticker=? AND timeframe=? AND candle_time=?',
                        row[:3],
                    ).fetchone()
                    if prior is not None:
                        counts['duplicate'] += 1
                        counts['changed_duplicate'] += prior != row[3:8]
                        continue
                    connection.execute('INSERT INTO candles_15m VALUES (?,?,?,?,?,?,?,?,?,?)', row)
                    connection.execute('INSERT INTO yahoo_import_metadata VALUES (?,?,?,?,?,?,?)',
                                       (*row[:3], run_id, source_timezone, 'UNVERIFIED', 'VALID_OHLCV'))
                    counts['new'] += 1
                connection.execute('UPDATE fetch_runs SET inserted=?,duplicate=? WHERE run_id=?',
                                   (counts['new'],counts['duplicate'],run_id))
            latest = max(valid_times, default='')
            status = 'OK' if valid_times else ('NO_VALID_ROWS' if frame is not None else 'ERROR')
            if status == 'OK' and expected_session and latest[:10] < expected_session:
                status = 'LATEST_SESSION_MISSING'
            result = dict(
                ticker=ticker, symbol=f'{ticker}.VN', attempted=True,
                status=status, expected_session=expected_session,
                requested=f'{days}d', period=period, valid=len(valid_times), **counts,
                first=min(valid_times,default=''), last=latest,
                source_timezone=source_timezone, started_at=started, fetched_at=fetched_at,
                run_id=run_id, errors=errors, rejected_counts=dict(rejected_counts), rejected=rejected,
            )
            summary.append(result)
            line = json.dumps(result, ensure_ascii=True)
            log_stream.write(line+'\n')
            log_stream.flush()
            print(line,flush=True)
            if args.evidence:
                args.evidence.mkdir(parents=True, exist_ok=True)
                with (args.evidence/f'{ticker}.csv').open('w',newline='',encoding='utf-8') as stream:
                    writer=csv.writer(stream)
                    writer.writerow(('ticker','timeframe','candle_time',*FIELDS,'source','fetched_at'))
                    writer.writerows(raw)
    return 1 if any(row['status'] != 'OK' for row in summary) else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('config.vn30.2026-07.json'))
    parser.add_argument('--days', type=int)
    parser.add_argument('--fallback-59', action='store_true')
    parser.add_argument('--scheduled', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    lock = args.config.resolve().parent / 'yahoo_15m.lock'
    with lock.open('a+b') as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.exit(3, f'Collector already running: {lock}\n')
        raise SystemExit(run(args))
