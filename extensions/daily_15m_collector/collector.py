"""Standalone append-only 15-minute OHLCV collector. Never opens QTA's original DB."""
import argparse,csv,json,sqlite3,sys,logging
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Ho_Chi_Minh')
DDL='''CREATE TABLE IF NOT EXISTS candles_15m (
 ticker TEXT NOT NULL,timeframe TEXT NOT NULL DEFAULT '15m',candle_time TEXT NOT NULL,
 open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,close REAL NOT NULL,
 volume REAL NOT NULL,source TEXT NOT NULL,fetched_at TEXT NOT NULL,
 PRIMARY KEY(ticker,timeframe,candle_time));
 CREATE TABLE IF NOT EXISTS fetch_runs(run_id INTEGER PRIMARY KEY AUTOINCREMENT,
 started_at TEXT NOT NULL,source TEXT NOT NULL,inserted INTEGER NOT NULL,
 duplicate INTEGER NOT NULL,invalid INTEGER NOT NULL,errors TEXT NOT NULL);'''

def normalize_time(value):
    if isinstance(value,datetime): dt=value
    else: dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('NAIVE_TIMESTAMP_NOT_ALLOWED')
    return dt.astimezone(TZ)

def validate(raw):
    ticker=str(raw['ticker']).strip().upper()
    if not ticker or not ticker.isalnum(): raise ValueError('INVALID_TICKER')
    when=normalize_time(raw['candle_time'])
    if when.minute%15 or when.second or when.microsecond: raise ValueError('OFF_GRID_TIME')
    from math import isfinite
    o,h,l,c,v=[float(raw[k]) for k in ('open','high','low','close','volume')]
    if not all(isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c,h):
        raise ValueError('INVALID_OHLCV')
    return (ticker,'15m',when.isoformat(),o,h,l,c,v,str(raw.get('source','UNKNOWN')),datetime.now(timezone.utc).isoformat())

def collect(db,items,source,log=None):
    path=Path(db);path.parent.mkdir(parents=True,exist_ok=True)
    added=duplicate=invalid=0;errors=[]
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript(DDL)
        for raw in items:
            try:
                d=validate(dict(raw,source=raw.get('source',source)))
                cur=con.execute('INSERT OR IGNORE INTO candles_15m VALUES (?,?,?,?,?,?,?,?,?,?)',d)
                added+=cur.rowcount;duplicate+=1-cur.rowcount
            except (ValueError,TypeError,KeyError,OverflowError) as e:
                invalid+=1;errors.append({'ticker':raw.get('ticker','?'),'time':str(raw.get('candle_time','?')),'error':str(e)})
        con.execute('INSERT INTO fetch_runs(started_at,source,inserted,duplicate,invalid,errors) VALUES(?,?,?,?,?,?)',
          (datetime.now(timezone.utc).isoformat(),source,added,duplicate,invalid,json.dumps(errors,ensure_ascii=False)))
    result=dict(source=source,inserted=added,duplicate=duplicate,invalid=invalid,errors=errors,db=str(path))
    if log:
        p=Path(log);p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('a',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
    return result

def yahoo_rows(symbols,days=5):
    try:import yfinance as yf
    except ImportError as e:raise RuntimeError('Install dependency: pip install yfinance') from e
    for sym in symbols:
        df=yf.Ticker(sym+'.VN').history(period=f'{min(days,59)}d',interval='15m',auto_adjust=False)
        if df is None or df.empty: raise RuntimeError('NO_PROVIDER_15M_DATA:'+sym)
        for t,r in df.iterrows():
            yield dict(ticker=sym,candle_time=t.to_pydatetime(),open=r['Open'],high=r['High'],low=r['Low'],close=r['Close'],volume=r['Volume'],source='YAHOO_FINANCE_YFINANCE')

def csv_rows(path):
    with open(path,encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default=str(Path(__file__).with_name('config.json')))
    p.add_argument('--csv',help='Offline import or testing; requires ticker,candle_time,open,high,low,close,volume')
    a=p.parse_args();cfg=json.loads(Path(a.config).read_text(encoding='utf-8'))
    base=Path(a.config).resolve().parent
    db=Path(cfg['database']);db=db if db.is_absolute() else base/db
    log=Path(cfg['log']);log=log if log.is_absolute() else base/log
    if a.csv:
        try:
            result=collect(db,csv_rows(a.csv),'CSV_IMPORT',log)
        except Exception as e:
            result={'error':str(e),'inserted':0,'source':'CSV_IMPORT'}
            log.parent.mkdir(parents=True,exist_ok=True)
            with log.open('a',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
            print(json.dumps(result,ensure_ascii=False));return 1
        print(json.dumps(result,ensure_ascii=False));return 0 if not result['invalid'] else 2
    # Per-symbol isolation: one provider outage must not discard other tickers.
    results=[];failure=[]
    for ticker in cfg['tickers']:
        try:
            rows=list(yahoo_rows([ticker],cfg.get('lookback_days',5)))
            result=collect(db,rows,'YAHOO_FINANCE_YFINANCE',log)
            result['ticker']=ticker
            results.append(result)
        except Exception as e:
            failure.append(dict(ticker=ticker,error=str(e)))
    summary=dict(source='YAHOO_FINANCE_YFINANCE',tickers_processed=len(results),
       tickers_failed=failure,inserted=sum(x['inserted'] for x in results),
       duplicate=sum(x['duplicate'] for x in results),invalid=sum(x['invalid'] for x in results))
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('a',encoding='utf-8') as f:f.write(json.dumps(summary,ensure_ascii=False)+'\n')
    print(json.dumps(summary,ensure_ascii=False));return 1 if failure else (2 if summary['invalid'] else 0)
if __name__=='__main__':sys.exit(main())
