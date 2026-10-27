"""Additive SQLite migrations and explicit, sourced reference imports."""
import sqlite3,hashlib,json,uuid
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

SCHEMAS={
'prices':('symbol,date,open,high,low,close,volume,basis,source,known_at','symbol,date'),
'universe':('security_id,symbol,exchange,sector,valid_from,valid_to,known_at,source','security_id,valid_from'),
'actions':('symbol,ex_date,kind,value,subscription_price,available_date,known_at,source','symbol,ex_date'),
'benchmarks':('symbol,date,close,source,known_at','symbol,date'),
'calendar':('date,source','date'),
'limits':('symbol,date,floor,ceiling,source','symbol,date'),
'coverage':('scope,symbol,start,end,source','scope,symbol,start')}
NUM={'open','high','low','close','volume','value','subscription_price','floor','ceiling'}
def connect(path,ro=False):
    return sqlite3.connect(Path(path).resolve().as_uri()+('?mode=ro' if ro else '?mode=rw'),uri=True,timeout=30)
def backup(path):
    p=Path(path);d=p.parent/'backups';d.mkdir(exist_ok=True)
    target=d/(p.stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.db')
    with connect(path,True) as src,sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity failed')
    return str(target)
def migrate(path,fail_after=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT name FROM sqlite_master WHERE name='QTA8_META'").fetchone():
            version=db.execute("SELECT value FROM QTA8_META WHERE key='version'").fetchone()
            if version and version[0]=='1':return {'status':'UNCHANGED','version':1}
            raise ValueError('Unknown Phase 8 schema version')
        saved=backup(path)
        db.execute('CREATE TABLE QTA8_META(key TEXT PRIMARY KEY,value TEXT)')
        for n,(kind,(fields,keys)) in enumerate(SCHEMAS.items()):
            cols=','.join(f'{c} '+('REAL' if c in NUM else 'TEXT')+' NOT NULL' for c in fields.split(','))
            db.execute(f'CREATE TABLE QTA8_{kind.upper()}({cols},PRIMARY KEY({keys}))')
            if fail_after==n:raise RuntimeError('Injected migration failure')
        db.execute('CREATE TABLE QTA8_IMPORTS(id TEXT PRIMARY KEY,kind TEXT,digest TEXT,rows INTEGER,created TEXT,backup TEXT)')
        db.execute("INSERT INTO QTA8_META VALUES('version','1')")
        db.commit()
    return {'status':'MIGRATED','version':1,'backup':saved}
def read(path,kind):
    fields=SCHEMAS[kind][0].split(',')
    with connect(path,True) as db:
        if not db.execute('SELECT name FROM sqlite_master WHERE name=?',('QTA8_'+kind.upper(),)).fetchone():return pd.DataFrame(columns=fields)
        return pd.read_sql_query('SELECT * FROM QTA8_'+kind.upper(),db)
def validate(kind,f):
    fields,keys=SCHEMAS[kind];f=f.copy()
    for c in f.columns:
        if c not in NUM:f[c]=f[c].fillna('')
    if set(fields.split(','))!=set(f.columns) or f.empty:raise ValueError('Sai cột hoặc CSV rỗng: '+fields)
    f=f[fields.split(',')]
    for col in f:
        if col in NUM:
            f[col]=pd.to_numeric(f[col],errors='raise')
            if not np.isfinite(f[col]).all():raise ValueError('Nonfinite '+col)
        else:f[col]=f[col].astype(str).str.strip()
        if col not in {'sector','valid_to'} and f[col].astype(str).eq('').any():raise ValueError('Thiếu '+col)
        if col in {'date','ex_date','available_date','known_at','valid_from','valid_to','start','end'}:
            nonblank=f[col].ne('');d=pd.to_datetime(f.loc[nonblank,col],format='%Y-%m-%d',errors='raise');f.loc[nonblank,col]=d.dt.strftime('%Y-%m-%d')
    if f.duplicated(keys.split(',')).any():raise ValueError('Trùng khóa')
    if 'symbol' in f and not f.symbol.str.fullmatch(r'[A-Z0-9^][A-Z0-9.^-]{0,29}').all():raise ValueError('Sai symbol')
    if kind=='prices':
        if not f.basis.eq('RAW_VND').all():raise ValueError('Chỉ nhận RAW_VND; không tự đoán đơn vị/điều chỉnh')
        if (f[['open','high','low','close']]<=0).any().any() or (f.volume<0).any() or (f.high<f[['open','close','low']].max(axis=1)).any() or (f.low>f[['open','close']].min(axis=1)).any():raise ValueError('OHLCV invalid')
    if kind in {'prices','benchmarks'}:
        if (f.date>pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').strftime('%Y-%m-%d')).any() or (f.known_at<f.date).any():raise ValueError('Future price / known_at before price')
    if kind=='benchmarks' and (f.close<=0).any():raise ValueError('Index <=0')
    if kind=='limits' and ((f.floor<=0)|(f.ceiling<f.floor)).any():raise ValueError('Invalid floor/ceiling')
    if kind=='coverage' and ((f.start>f.end)|~f.scope.isin(['UNIVERSE','ACTIONS'])).any():raise ValueError('Invalid coverage')
    if kind=='universe':
        if (~f.exchange.isin(['HOSE','HNX','UPCOM'])).any() or ((f.valid_to!='')&(f.valid_to<f.valid_from)).any():raise ValueError('Invalid universe interval')
        for key in ['security_id','symbol']:
            for _,g in f.groupby(key):
                g=g.sort_values('valid_from');ends=g.valid_to.replace('','9999-12-31').to_numpy()
                if len(g)>1 and (g.valid_from.to_numpy()[1:]<=ends[:-1]).any():raise ValueError('Overlapping universe intervals')
    if kind=='actions':
        if (~f.kind.isin(['CASH','BONUS','SPLIT','RIGHTS'])).any() or (f.value<=0).any() or (f.subscription_price<0).any() or (f.available_date<f.ex_date).any() or (f.known_at>f.ex_date).any():raise ValueError('Invalid action / chưa biết quyền tại ex-date')
    return f

def ingest(path,kind,f,allow_revisions=False):
    f=validate(kind,f);migrate(path);fields,keys=SCHEMAS[kind];cols=fields.split(',');pk=keys.split(',')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        old=pd.read_sql_query('SELECT * FROM QTA8_'+kind.upper(),db)
        combined=(f.copy() if old.empty else pd.concat([old,f],ignore_index=True)).drop_duplicates(pk,keep='last');validate(kind,combined)
        oldmap={tuple(r[k] for k in pk):r for r in old.to_dict('records')};changes=[]
        for r in f.to_dict('records'):
            prior=oldmap.get(tuple(r[k] for k in pk))
            if prior==r:continue
            if prior is not None and not allow_revisions:raise ValueError('Revision yêu cầu --allow-revisions')
            changes.append(tuple(r[c] for c in cols))
        if not changes:return {'status':'UNCHANGED','rows':0}
        saved=backup(path)
        db.executemany('INSERT OR REPLACE INTO QTA8_'+kind.upper()+'('+fields+') VALUES('+','.join('?' for _ in cols)+')',changes)
        digest=hashlib.sha256(f.to_csv(index=False).encode()).hexdigest()
        db.execute('INSERT INTO QTA8_IMPORTS VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,kind,digest,len(changes),datetime.now().isoformat(),saved));db.commit()
    return {'status':'IMPORTED','rows':len(changes),'backup':saved}

def members(universe,day,known_by=None):
    d=str(pd.Timestamp(day).date());k=str(pd.Timestamp(known_by or day).date())
    return universe.loc[(universe.valid_from<=d)&((universe.valid_to=='')|(universe.valid_to>=d))&(universe.known_at<=k)]
def covered(ref,scope,symbol,start,end):
    g=ref.loc[(ref.scope==scope)&ref.symbol.eq(symbol)&ref.start.le(str(start)[:10])&ref.end.ge(str(end)[:10])]
    return not g.empty

def adjusted(raw,actions,asof,causal=False):
    """Keep raw OHLC; backward display or forward-rescaled causal research prices."""
    f=raw.sort_values('date').loc[lambda x:x.date<=str(asof)[:10]].copy();factor=np.ones(len(f));events=[]
    for a in actions.loc[(actions.ex_date<=str(asof)[:10])&(actions.known_at<=actions.ex_date)].sort_values('ex_date').itertuples():
        prior=f.loc[f.date<a.ex_date]
        if prior.empty:continue
        p=float(prior.close.iloc[-1]);k=1.
        if a.kind=='CASH':k=(p-a.value)/p
        elif a.kind=='SPLIT':k=1/a.value
        elif a.kind=='BONUS':k=1/(1+a.value)
        elif a.kind=='RIGHTS':k=(p+a.value*a.subscription_price)/(p*(1+a.value))
        if not 0<k<100:raise ValueError('Invalid adjustment factor')
        factor*=np.where(f.date>=a.ex_date,1/k,1) if causal else np.where(f.date<a.ex_date,k,1)
        events.append({'ex_date':a.ex_date,'kind':a.kind,'factor':k})
    for c in ['open','high','low','close']:f['adj_'+c]=f[c]*factor
    return f,events

def update_plan(path):
    with connect(path,True) as db:r=pd.read_sql_query('SELECT SYMBOL symbol,MAX(TRADE_DATE) last_date FROM STOCK_PRICES GROUP BY SYMBOL',db)
    p=read(path,'prices')
    if not p.empty:
        # Provider RAW series are separate; legacy values cannot certify RAW coverage.
        r=pd.concat([r,p.groupby('symbol').date.max().rename('last_date').reset_index()]).groupby('symbol',as_index=False).last_date.max()
    r['start']=(pd.to_datetime(r.last_date)+pd.Timedelta(days=1)).dt.strftime('%Y-%m-%d');r['mode']='APPEND_ONLY; quyền/revision cần kiểm tra lại lịch sử';return r
