import json,sqlite3,hashlib
import numpy as np
import pandas as pd
import pytest
from src.phase8 import data,fast,research,execution

def universe():return pd.DataFrame([dict(security_id='ISIN1',symbol='AAA',exchange='HOSE',sector='',valid_from='2020-01-01',valid_to='',known_at='2020-01-01',source='fixture')])
def raw(n=300):
    d=pd.bdate_range('2020-01-01',periods=n).strftime('%Y-%m-%d');c=10000+np.arange(n)*2+np.sin(np.arange(n))*40
    return pd.DataFrame(dict(symbol='AAA',date=d,open=c,high=c+200,low=c-200,close=c+10,volume=100000,basis='RAW_VND',source='fixture',known_at=d))
def database(tmp_path):
    p=tmp_path/'old.db'
    with sqlite3.connect(p) as db:db.execute('CREATE TABLE legacy(id INT,value TEXT)');db.execute("INSERT INTO legacy VALUES(1,'keep')")
    return p

def test_migration_backup_and_idempotence(tmp_path):
    p=database(tmp_path);r=data.migrate(p)
    for f in [p,r['backup']]:
        with sqlite3.connect(f) as db:assert db.execute('SELECT * FROM legacy').fetchall()==[(1,'keep')];assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert data.migrate(p)['status']=='UNCHANGED'
    with sqlite3.connect(r['backup']) as db:assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'QTA8_%'").fetchall()
def test_migration_failure_atomic(tmp_path):
    p=database(tmp_path)
    with pytest.raises(RuntimeError):data.migrate(p,fail_after=2)
    with sqlite3.connect(p) as db:assert db.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()==[('legacy',)]
def test_import_revision_backup(tmp_path):
    p=database(tmp_path);f=raw(2);assert data.ingest(p,'prices',f)['rows']==2
    assert data.ingest(p,'prices',f)['rows']==0
    f.loc[0,'close']+=1
    with pytest.raises(ValueError):data.ingest(p,'prices',f)
    assert data.ingest(p,'prices',f,True)['rows']==1
@pytest.mark.parametrize('col,value',[('close',np.nan),('high',1),('volume',-1),('basis','ADJUSTED'),('date','2099-01-01'),('source','')])
def test_invalid_prices(col,value):
    f=raw(2);f.loc[0,col]=value
    with pytest.raises((ValueError,TypeError)):data.validate('prices',f)
def test_point_in_time_rename_delisting():
    u=universe();u.loc[0,'valid_to']='2020-03-01';r=u.iloc[0].copy();r['symbol']='BBB';r['valid_from']='2020-03-02';r['valid_to']='2020-05-01';r['known_at']='2020-03-02';u=pd.concat([u,pd.DataFrame([r])]);data.validate('universe',u)
    assert data.members(u,'2020-02-01').symbol.tolist()==['AAA'];assert data.members(u,'2020-04-01').symbol.tolist()==['BBB'];assert data.members(u,'2020-06-01').empty
    assert data.members(u,'2020-04-01','2020-02-01').empty

def test_universe_overlap_rejected():
    u=universe();r=u.iloc[0].copy();r.valid_from='2020-02-01'
    with pytest.raises(ValueError):data.validate('universe',pd.concat([u,pd.DataFrame([r])]))
def action(kind='SPLIT',value=2):return pd.DataFrame([dict(symbol='AAA',ex_date='2020-01-03',kind=kind,value=value,subscription_price=5000,available_date='2020-01-07',known_at='2020-01-01',source='fixture')])
@pytest.mark.parametrize('kind,value,k',[('SPLIT',2,.5),('BONUS',1,.5),('CASH',100,.99)])
def test_adjustments_preserve_raw_and_future_prefix(kind,value,k):
    f=raw(5);f[['open','high','low','close']]=[10000,10200,9800,10000];a=action(kind,value)
    before,_=data.adjusted(f,a,'2020-01-02');assert np.all(before.adj_close==10000)
    back,_=data.adjusted(f,a,'2020-01-07');assert back.adj_close.iloc[0]==10000*k;assert back.close.iloc[0]==10000
    forward,_=data.adjusted(f,a,'2020-01-07',causal=True);assert forward.adj_close.iloc[0]==10000
    prefix,_=data.adjusted(f,a,'2020-01-02',causal=True);pd.testing.assert_series_equal(prefix.adj_close,forward.adj_close.iloc[:2])
def test_rights_adjustment():
    f=raw(5);f['close']=10000;r,_=data.adjusted(f,action('RIGHTS',1),'2020-01-07');assert r.adj_close.iloc[0]==7500

def test_fast_math_parity():
    from src.phase7.features import features
    f=raw(300);a=f[['open','high','low','close','volume']].to_numpy();r=fast.latest(a);g=f.rename(columns={'open':'OPEN_PRICE','high':'HIGH_PRICE','low':'LOW_PRICE','close':'CLOSE_PRICE','volume':'VOLUME'});i=features(g).iloc[-1]
    assert r['score']==pytest.approx(i.adaptive_score);assert r['adx']==pytest.approx(i.adx);assert r['rsi']==pytest.approx(i.rsi14);assert r['atr']==pytest.approx(i.atr14)
def test_fast_missing_and_zero_division():
    f=raw(300);a=f[['open','high','low','close','volume']].to_numpy();a[:,:4]=10000;a[:,4]=0;r=fast.latest(a);assert r['rsi']==50;json.dumps(r,allow_nan=False);a[0,0]=np.nan;assert fast.latest(a)['status']=='INVALID'
def test_fast_prefix_no_future():
    f=raw(300);a=f[['open','high','low','close','volume']].to_numpy();r=fast.latest(a[:250]);a[250:]*=20;assert fast.latest(a[:250])==r

def test_purge_embargo_dates():
    d=pd.bdate_range('2010-01-01',periods=2200);x=pd.DataFrame({'date':d[:-20],'end':d[20:]});parts=list(research.split_dates(d,horizon=20,embargo=20))
    for p in parts:
        tr=research.purged_ids(x,p['train'],p['validation'][0]);va=research.purged_ids(x,p['validation'],p['test'][0]);assert x.loc[tr,'end'].max()<p['validation'][0];assert x.loc[va,'end'].max()<p['test'][0];assert d.get_loc(p['validation'][0])-d.get_loc(p['train'][1])>=20

def test_rolling_window_and_prefix_splits():
    d=pd.bdate_range('2010-01-01',periods=2500);a=list(research.split_dates(d[:2200],mode='rolling'));b=list(research.split_dates(d,mode='rolling'));assert a[0]==b[0];assert b[-1]['train'][0]>b[0]['train'][0]
def test_inference_multiple_testing_and_too_few():
    assert research.inference([1,2])['p_adjusted'] is None
    a=np.random.default_rng(4).normal(.01,.03,200);r=research.inference(a,1);s=research.inference(a,4);assert s['p_adjusted']==min(1,r['p_adjusted']*4)
def test_permutation_reproducible_and_preserves_frequency():
    o=pd.DataFrame([{'date':d,'net':j/100,'selected':j==3} for d in range(100) for j in range(4)]);r=research.permutation(o,runs=99);assert r==research.permutation(o,runs=99);assert r['excess']==pytest.approx(.015);assert r['dates']==100
    o.selected=True;assert research.permutation(o)['dates']==0
@pytest.mark.parametrize('ok,n,mean,p,expected',[(False,200,.02,.001,'Chưa đủ bằng chứng'),(True,20,.02,.001,'Chưa đủ bằng chứng'),(True,200,.02,.001,'Có bằng chứng'),(True,200,-.02,.001,'Bằng chứng ngược'),(True,200,.02,.5,'Chưa đủ bằng chứng')])
def test_evidence_three_levels(ok,n,mean,p,expected):
    c={k:dict(dates=200,mean_difference=mean,p_adjusted=p) for k in ['VNINDEX','eligible_buy_hold','MA50']};perm=dict(dates=200,excess=.02,p_adjusted=p);assert research.evidence(c,perm,ok,n)[0]==expected

def replay_fixture():
    days=pd.bdate_range('2020-01-01',periods=6).strftime('%Y-%m-%d').tolist();b=pd.DataFrame([dict(symbol='AAA',date=d,phase=p,open=10000,high=11000,low=9000,close=10000,volume=100000,floor=9300,ceiling=10700) for d in days for p in ['AM','PM']]);return days,b

def order(day,side,phase='AM',qty=100):return dict(symbol='AAA',date=day,signal_date='2019-12-31',side=side,phase=phase,qty=qty)
def test_t2_and_cash_settlement():
    days,b=replay_fixture();orders=[order(days[0],'BUY'),order(days[1],'SELL'),order(days[2],'SELL'),order(days[2],'SELL','PM')];r=execution.replay(b,orders,days,universe());assert len(r['fills'])==2;assert r['fills'][-1]['phase']=='PM';assert r['equity'][2]['receivable']>0;assert r['equity'][4]['receivable']==0
@pytest.mark.parametrize('side,price',[('BUY',10700),('SELL',9300)])
def test_locked_limits(side,price):
    days,b=replay_fixture();b.loc[b.date==days[3],['open','high','low','close']]=price;orders=[order(days[0],'BUY'),order(days[3],side)];r=execution.replay(b,orders,days,universe());assert any(x['reason']=='locked_limit' for x in r['rejections'])
def test_participation_aggregate():
    days,b=replay_fixture();r=execution.replay(b,[order(days[0],'BUY',qty=1000),order(days[0],'BUY',qty=1000)],days,universe());assert sum(x['filled_qty'] for x in r['fills'])==1000
@pytest.mark.parametrize('price,exchange,step',[(9999,'HOSE',10),(10000,'HOSE',50),(50000,'HOSE',100),(9999,'HNX',100),(1234,'UPCOM',100)])
def test_tick(price,exchange,step):assert execution.tick(price,exchange)==step

def test_no_same_day_signal_or_odd_lot():
    days,b=replay_fixture();o=order(days[0],'BUY');o['signal_date']=days[0]
    with pytest.raises(ValueError):execution.replay(b,[o],days,universe())
    with pytest.raises(ValueError):execution.replay(b,[order(days[0],'BUY',qty=1)],days,universe())
def test_costs_and_ideal_gap():
    days,b=replay_fixture();r=execution.compare(b,[order(days[0],'BUY'),order(days[3],'SELL')],days,universe());assert r['return_gap']<0

def test_corporate_cash_payment():
    days,b=replay_fixture();a=action('CASH',100);r=execution.replay(b,[order(days[0],'BUY')],days,universe(),a);assert r['equity'][2]['receivable']==10000;assert r['equity'][4]['receivable']==0

def test_split_and_bonus_qty():
    days,b=replay_fixture();a=action('SPLIT',2);b.loc[b.date>='2020-01-03',['open','high','low','close','floor','ceiling']]/=2
    r=execution.replay(b,[order(days[0],'BUY'),order(days[4],'SELL','PM',200)],days,universe(),a);assert r['fills'][-1]['filled_qty']==200

def test_api_auth(signed_client):
    assert signed_client.get('/phase8').status_code==200
    assert signed_client.post('/api/p8/research',json={'symbols':[]}).status_code==422

def test_pooled_first_oos_window_unchanged_by_future_prices(tmp_path):
    p=tmp_path/'research.db';rng=np.random.default_rng(7);d=pd.bdate_range('2010-01-01',periods=2200);rows=[]
    for symbol in ['AAA','BBB']:
        c=10000*np.exp(np.cumsum(rng.normal(0,.02,len(d))))
        rows.extend((symbol,str(date.date()),v,v*1.03,v*.97,v,100000,'VALID') for date,v in zip(d,c))
    with sqlite3.connect(p) as db:
        db.execute('CREATE TABLE STOCK_PRICES(SYMBOL TEXT,TRADE_DATE TEXT,OPEN_PRICE REAL,HIGH_PRICE REAL,LOW_PRICE REAL,CLOSE_PRICE REAL,VOLUME REAL,QUALITY_STATUS TEXT)');db.executemany('INSERT INTO STOCK_PRICES VALUES(?,?,?,?,?,?,?,?)',rows)
    a=research.run(p,['AAA','BBB'],registry=str(tmp_path/'registry.db'))
    with sqlite3.connect(p) as db:db.execute('UPDATE STOCK_PRICES SET OPEN_PRICE=OPEN_PRICE*2,HIGH_PRICE=HIGH_PRICE*2,LOW_PRICE=LOW_PRICE*2,CLOSE_PRICE=CLOSE_PRICE*2 WHERE TRADE_DATE>=?',(str(d[1900].date()),))
    b=research.run(p,['AAA','BBB'],registry=str(tmp_path/'registry.db'))
    aa=[r for r in a['observations'] if r['fold']==1];bb=[r for r in b['observations'] if r['fold']==1]
    assert aa and aa==bb

def test_day_open_cannot_sell_at_t2_without_pm_bar():
    days,b=replay_fixture();b=b.loc[b.phase=='AM'].copy();b.phase='OPEN';o=[order(days[0],'BUY','OPEN'),order(days[2],'SELL','OPEN'),order(days[3],'SELL','OPEN')];r=execution.replay(b,o,days,universe());assert [f['date'] for f in r['fills']]==[days[0],days[3]]

def test_rights_cash_and_availability():
    days,b=replay_fixture();a=action('RIGHTS',1);r=execution.replay(b,[order(days[0],'BUY'),order(days[4],'SELL','PM',200)],days,universe(),a,exercise_rights=True);assert r['fills'][-1]['filled_qty']==200
    skipped=execution.replay(b,[order(days[0],'BUY')],days,universe(),a);assert any(x['reason']=='rights_not_exercised' for x in skipped['rejections'])

def test_missing_calendar_order_rejected():
    days,b=replay_fixture()
    with pytest.raises(ValueError):execution.replay(b,[order('2020-12-31','BUY')],days,universe())

def test_no_daily_and_intraday_double_count():
    days,b=replay_fixture();r=b.iloc[0].copy();r.phase='OPEN';b=pd.concat([b,pd.DataFrame([r])])
    with pytest.raises(ValueError):execution.replay(b,[],days,universe())

def test_cache_recomputes_only_changed_symbol(tmp_path):
    p=tmp_path/'cacheprices.db';f=raw(300)
    with sqlite3.connect(p) as db:
        db.execute('CREATE TABLE STOCK_PRICES(SYMBOL TEXT,TRADE_DATE TEXT,OPEN_PRICE REAL,HIGH_PRICE REAL,LOW_PRICE REAL,CLOSE_PRICE REAL,VOLUME REAL)')
        for symbol in ['AAA','BBB']:db.executemany('INSERT INTO STOCK_PRICES VALUES(?,?,?,?,?,?,?)',[(symbol,*r) for r in f[['date','open','high','low','close','volume']].itertuples(index=False,name=None)])
    cache=str(tmp_path/'features.db');assert fast.scan(p,cache)['computed']==2;assert fast.scan(p,cache)['computed']==0
    with sqlite3.connect(p) as db:db.execute('UPDATE STOCK_PRICES SET VOLUME=VOLUME+1 WHERE SYMBOL="AAA" AND TRADE_DATE=?',(f.date.iloc[-1],))
    assert fast.scan(p,cache)['computed']==1
