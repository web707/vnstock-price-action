import json,sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.phase7.features import features,weekly
from src.phase7.model import partitions,walk_forward,bootstrap
from src.phase7.portfolio import simulate,metrics
from src.phase7 import store
from import_phase7_reference import validate

def prices(n=2200,seed=7):
    rng=np.random.default_rng(seed);c=100*np.exp(np.cumsum(rng.normal(.0003,.012,n)))
    return pd.DataFrame({'TRADE_DATE':pd.bdate_range('2014-01-01',periods=n),'OPEN_PRICE':c*.999,'HIGH_PRICE':c*1.02,'LOW_PRICE':c*.98,'CLOSE_PRICE':c,'ADJ_CLOSE':c,'VOLUME':500000,'QUALITY_STATUS':'VALID','SOURCE':'test'})

def test_features_causal_prefix():
    f=prices(400);a=features(f.iloc[:300]);b=features(f);pd.testing.assert_frame_equal(a,b.iloc[:300])
    for k in range(6,len(f)):
        if b.swing_high_confirmed.iloc[k]:assert b.resistance.iloc[k]==f.HIGH_PRICE.iloc[k-3]
    assert b.adaptive_score.dropna().between(0,100).all()

def test_flat_zero_volume_no_inf():
    f=prices(300);f[['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE']]=100;f.VOLUME=0;i=features(f)
    assert not np.isinf(i.select_dtypes('number').to_numpy()).any()
    assert i.adx.dropna().eq(0).all();assert features(f.iloc[:3]).adaptive_score.isna().all()

def test_weekly_closed_only():
    f=prices(40);today='2014-02-12';a=weekly(f,today);b=weekly(f.iloc[:30],today)
    pd.testing.assert_frame_equal(a,b);assert a.TRADE_DATE.max()<pd.Timestamp(today)

def test_purged_splits_frozen_oos_and_contributions():
    f=prices()
    for p in partitions(len(f)):
        assert p['train'][1]-1+10<p['validation'][0];assert p['validation'][1]-1+10<p['test'][0]
    a=walk_forward(f.iloc[:1600]);b=walk_forward(f)
    first=[x for x in a['observations'] if x['fold']==1];assert first==[x for x in b['observations'] if x['fold']==1]
    pred=b['prediction'];assert pred
    logit=pred['intercept_log_odds']+sum(pred['contributions_log_odds'].values());assert 1/(1+np.exp(-logit))==pytest.approx(pred['probability'])
    assert sum(x['count'] for x in b['calibration_bins'])==b['oos_samples']

def test_model_abstains_short_oneclass_stale():
    assert walk_forward(prices(100))['status']=='INSUFFICIENT_DATA'
    f=prices();f[['OPEN_PRICE','CLOSE_PRICE']]=100;f.HIGH_PRICE=102;f.LOW_PRICE=98
    assert walk_forward(f)['prediction'] is None
    f=prices();f.loc[1600:,'QUALITY_STATUS']='UNKNOWN';r=walk_forward(f)
    assert r['prediction'] is None and r['abstention_reason']

def fixed(monkeypatch,n=12):
    import src.phase7.portfolio as p
    f=prices(n);f[['OPEN_PRICE','CLOSE_PRICE']]=100;f.HIGH_PRICE=102;f.LOW_PRICE=98
    monkeypatch.setattr(p,'features',lambda f:pd.DataFrame({'adaptive_score':[100]+[0]*(len(f)-1),'atr14':1.,'avg_volume20':500000.},index=f.index));return f

def test_settlement_risk_and_locked_ceiling(monkeypatch):
    f=fixed(monkeypatch);r=simulate({'AAA':f},{'AAA':'HOSE'},strict=False,rebalance=1)
    assert r['trades'];t=r['trades'][0];assert t['holding_sessions']>=3
    assert t['qty']*t['entry']*1.0015<=1e8*.2
    assert min(e['cash'] for e in r['equity'])>=0
    f.loc[1,['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE']]=107
    r=simulate({'AAA':f},{'AAA':'HOSE'},strict=False,rebalance=1);assert not r['trades'];assert r['skips']['locked_ceiling']==1

def test_strict_calendar_and_missing_limits(monkeypatch):
    f=fixed(monkeypatch);limits=pd.DataFrame({'DATE':f.TRADE_DATE,'SYMBOL':'AAA','FLOOR':93.,'CEILING':107.})
    with pytest.raises(ValueError):simulate({'AAA':f},{},strict=True)
    r=simulate({'AAA':f},{},strict=True,calendar=f.TRADE_DATE,limits=limits,rebalance=1);assert r['trades']
    r=simulate({'AAA':f},{},strict=True,calendar=f.TRADE_DATE,limits=limits.drop(index=1),rebalance=1);assert not r['trades'];assert r['skips']['missing_price_limits']

def test_portfolio_prefix():
    f=prices(400);a=simulate({'AAA':f.iloc[:320]},{'AAA':'HOSE'},strict=False,threshold=30);b=simulate({'AAA':f},{'AAA':'HOSE'},strict=False,threshold=30)
    assert a['equity']==b['equity'][:len(a['equity'])]

def test_metrics_and_bootstrap():
    r=metrics([{'date':'2020-01-01','equity':100},{'date':'2021-01-01','equity':100}],[]);assert r['cagr']==0 and r['sharpe'] is None and r['profit_factor'] is None
    assert bootstrap([.1])['status']=='INSUFFICIENT_SAMPLES';assert bootstrap([.01,-.02]*20)==bootstrap([.01,-.02]*20)

def test_user_isolation_alert_dedup(tmp_path,monkeypatch):
    monkeypatch.setenv('QTA_USER_DB',str(tmp_path/'users.db'));store.watch('a','HPG');assert not store.watches('b')
    assert not store.poll('a',{'HPG':{'state':1}});assert len(store.poll('a',{'HPG':{'state':2}}))==1;assert len(store.poll('a',{'HPG':{'state':2}}))==1
    store.journal('a',{'entry':1});assert not store.journal('b');store.filters('a',{'search':'HPG'});assert not store.filters('b')

def test_reference_validation():
    with pytest.raises(ValueError):validate('benchmark',pd.DataFrame({'DATE':['2020-01-01']*2,'CLOSE':[100,101],'SOURCE':['x','x']}))
    with pytest.raises(ValueError):validate('units',pd.DataFrame({'SYMBOL':['AAA'],'UNIT':['VND'],'BASIS':['ADJUSTED'],'SOURCE':['x']}))
    with pytest.raises(ValueError):validate('sectors',pd.DataFrame({'SYMBOL':['AAA']*2,'SECTOR':['a','b'],'VALID_FROM':['2020-01-01','2021-01-01'],'VALID_TO':[None,None],'SOURCE':['x']*2}))

def test_pdf_csv():
    from src.phase7.reports import pdf_bytes,csv_bytes
    from pypdf import PdfReader
    import io
    pdf=pdf_bytes('Báo cáo cổ phiếu',[{'Mã':'HPG','Điểm':50}],['Dữ liệu chưa xác minh']);assert 'cổ phiếu' in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "'=cmd" in csv_bytes([{'x':'=cmd'}]).decode('utf-8-sig')

def small_db(path):
    with sqlite3.connect(path) as db:
        pd.DataFrame({'SYMBOL':['AAA','BBB','CCC'],'COMPANY_NAME':['A','B','C'],'EXCHANGE':['HOSE']*3}).to_sql('STOCK_SYMBOLS',db,index=False)
        a=prices(300);a['SYMBOL']='AAA';b=prices(300,8);b['SYMBOL']='BBB';pd.concat([a,b]).to_sql('STOCK_PRICES',db,index=False)
        pd.DataFrame(columns=['SYMBOL','EVENT_DATE','EVENT_TYPE','EVENT_VALUE','SOURCE']).to_sql('STOCK_EVENTS',db,index=False)

def test_dashboard_rs_health(tmp_path,monkeypatch):
    from src.phase7 import service
    p=tmp_path/'prices.db';small_db(p);ref=tmp_path/'reference';ref.mkdir();monkeypatch.setenv('QTA_REFERENCE_DIR',str(ref))
    f=prices(300);pd.DataFrame({'DATE':f.TRADE_DATE,'CLOSE':f.CLOSE_PRICE,'SOURCE':'test'}).to_csv(ref/'benchmark.csv',index=False)
    pd.DataFrame({'SYMBOL':['AAA','BBB'],'SECTOR':['steel']*2,'VALID_FROM':['2010-01-01']*2,'VALID_TO':[None,None],'SOURCE':['test']*2}).to_csv(ref/'sectors.csv',index=False)
    r=service.dashboard(p);assert r['missing_symbols']==['CCC'];assert r['breadth50']['denominator']==2
    assert all(x['rs_percentile'] is not None for x in r['items']);assert len(r['sectors'])==1
    assert service.health(p,'AAA')['missing_sessions'] is None;assert service.compare(p,['AAA','BBB'])['sessions']==252
    assert service.dashboard(p)['cache_hit']

def test_api_auth_csrf_and_bad_journal(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from src.web.app import app
    from src.phase7 import api
    p=tmp_path/'p.db';small_db(p);monkeypatch.setattr(api,'path',lambda:p);monkeypatch.setenv('QTA_AUTH_DB',str(tmp_path/'auth.db'));monkeypatch.setenv('QTA_USER_DB',str(tmp_path/'u.db'))
    with TestClient(app) as c:
        assert c.get('/api/p7/dashboard').status_code==401
        data={'username':'phase7tester','password':'safe-test-pass-123'};assert c.post('/api/auth/register',json=data).status_code==201;assert c.post('/api/auth/login',json=data).status_code==200
        token=c.get('/api/auth/me').json()['csrf'];h={'X-CSRF-Token':token}
        assert c.post('/api/p7/watch',json={'symbol':'AAA'}).status_code==403
        assert c.post('/api/p7/watch',json={'symbol':'AAA'},headers=h).status_code==200
        assert c.post('/api/p7/journal',json={'symbol':'AAA','entry_date':'2020-01-02','exit_date':'2019-01-01','entry':100,'exit':90,'qty':100},headers=h).status_code==422
        assert c.post('/api/p7/portfolio',json={'symbols':['AAA'],'risk_trade':1},headers=h).status_code==422
        assert c.get('/phase7').status_code==200

def test_volume_dryup_breakout_and_ad(monkeypatch):
    f=prices(300);f[['OPEN_PRICE','CLOSE_PRICE']]=100;f.HIGH_PRICE=101;f.LOW_PRICE=99;f.VOLUME=1000
    f.loc[295:,'VOLUME']=100;i=features(f);assert i.dry_up.iloc[-1];assert i.ad.iloc[-1]==0
    f.loc[299,['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','VOLUME']]=[101,105,100,104,10000]
    assert features(f).breakout.iloc[-1]==1

def test_missing_sessions_and_benchmark_alignment(tmp_path,monkeypatch):
    from src.phase7 import service
    p=tmp_path/'p.db';small_db(p);ref=tmp_path/'ref';ref.mkdir();monkeypatch.setenv('QTA_REFERENCE_DIR',str(ref));f=prices(300)
    pd.DataFrame({'DATE':f.TRADE_DATE,'SOURCE':'test'}).to_csv(ref/'calendar.csv',index=False)
    with sqlite3.connect(p) as db:db.execute('DELETE FROM STOCK_PRICES WHERE SYMBOL=? AND TRADE_DATE=?',('AAA',str(f.TRADE_DATE.iloc[100])))
    assert str(f.TRADE_DATE.iloc[100].date()) in service.health(p,'AAA')['missing_sessions']
    # Deliberately incomplete index reference must not become a filled benchmark.
    pd.DataFrame({'DATE':f.TRADE_DATE.iloc[:20],'CLOSE':f.CLOSE_PRICE.iloc[:20],'SOURCE':'test'}).to_csv(ref/'benchmark.csv',index=False)
    r=service.dashboard(p);assert all(x.get('rs_benchmark') is None for x in r['items'])

def test_invalid_ohlcv_rejected(tmp_path,monkeypatch):
    from src.phase7 import service
    p=tmp_path/'p.db';small_db(p);monkeypatch.setenv('QTA_REFERENCE_DIR',str(tmp_path/'none'))
    with sqlite3.connect(p) as db:db.execute("UPDATE STOCK_PRICES SET HIGH_PRICE=0 WHERE SYMBOL='AAA'")
    with pytest.raises(ValueError):service.detail(p,'AAA')
    assert next(x for x in service.dashboard(p)['items'] if x['symbol']=='AAA')['status']=='INVALID'
