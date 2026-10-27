import os,time,sqlite3
from pathlib import Path
from threading import RLock
import pandas as pd
import numpy as np
from src.config import settings
from src.discovery import db_revision
from src.data_quality import assess
_cache={};_lock=RLock()
def refdir():return Path(os.getenv('QTA_REFERENCE_DIR',str(settings.state_dir.parent/'reference')))
def reference(name):
    p=refdir()/(name+'.csv')
    if not p.exists():return pd.DataFrame()
    return pd.read_csv(p)
def ref_signature():return tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(refdir().glob('*.csv')))
def safe(x):
    if isinstance(x,dict):return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [safe(v) for v in x]
    if isinstance(x,np.bool_):return bool(x)
    if isinstance(x,np.integer):return int(x)
    if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
    if isinstance(x,pd.Timestamp):return x.isoformat()
    return x

def snapshot(path):
    rev=db_revision(path);today=pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date();key=(rev,today)
    with _lock:
        if rev and _cache.get('key')==key and time.monotonic()-_cache.get('time',0)<120:return _cache['value']
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        f=pd.read_sql_query('SELECT * FROM STOCK_PRICES ORDER BY SYMBOL,TRADE_DATE',db)
        catalog=pd.read_sql_query('SELECT SYMBOL,COMPANY_NAME,EXCHANGE FROM STOCK_SYMBOLS',db)
        events=pd.read_sql_query('SELECT * FROM STOCK_EVENTS',db)
    f.TRADE_DATE=pd.to_datetime(f.TRADE_DATE,errors='coerce');f=f.loc[f.TRADE_DATE<pd.Timestamp(today)]
    value={'frames':{s:g.reset_index(drop=True) for s,g in f.groupby('SYMBOL',sort=False)},'catalog':catalog,'events':events}
    if rev and rev==db_revision(path):
        with _lock:_cache.update(key=key,time=time.monotonic(),value=value)
    return value

def valid(f):return assess(f)['status']!='INVALID'
def benchmark():
    f=reference('benchmark')
    if not {'DATE','CLOSE','SOURCE'}.issubset(f) or f.empty:return None
    d=pd.to_datetime(f.DATE,errors='coerce');c=pd.to_numeric(f.CLOSE,errors='coerce')
    if d.isna().any() or d.duplicated().any() or (~np.isfinite(c)).any() or (c<=0).any() or f.SOURCE.fillna('').eq('').any():raise ValueError('benchmark.csv không hợp lệ')
    return pd.Series(c.to_numpy(),index=d).sort_index()
def sector_at(ref,symbol,day):
    if ref.empty:return None
    start=pd.to_datetime(ref.VALID_FROM);end=pd.to_datetime(ref.VALID_TO).fillna(pd.Timestamp.max)
    rows=ref.loc[ref.SYMBOL.eq(symbol)&start.le(day)&end.ge(day)]
    return str(rows.iloc[0].SECTOR) if len(rows)==1 else None
