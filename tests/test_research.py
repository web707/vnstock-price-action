import numpy as np
import pandas as pd
import pytest
from src.research import indicators, analyze, size_position


def prices(n=250,flat=False):
    c=np.full(n,100.) if flat else np.arange(n,dtype=float)+100
    return pd.DataFrame({'TRADE_DATE':pd.bdate_range('2024-01-01',periods=n),
        'OPEN_PRICE':c,'HIGH_PRICE':c+1,'LOW_PRICE':c-1,'CLOSE_PRICE':c,
        'VOLUME':np.full(n,100000),'QUALITY_STATUS':'VALID','SOURCE':'test','ADJ_CLOSE':c})


def test_indicators_flat_and_rising():
    flat=indicators(prices(flat=True)).iloc[-1]
    assert flat.rsi14==50 and flat.atr14==2 and flat.macd_hist==0
    rise=indicators(prices()).iloc[-1]
    assert rise.rsi14==100 and rise.ma20==pytest.approx(np.mean(np.arange(330,350)))


def test_prefix_invariance_no_future_leakage():
    f=prices();prefix=indicators(f.iloc[:210]);full=indicators(f)
    pd.testing.assert_frame_equal(prefix,full.iloc[:210])
    changed=f.copy();changed.loc[210:,'CLOSE_PRICE']=10000
    pd.testing.assert_frame_equal(prefix,indicators(changed).iloc[:210])


def test_breakout_uses_previous_high_volume_baseline():
    f=prices(flat=True);f.loc[249,['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','VOLUME']]=[110,112,109,111,200000]
    i=indicators(f).iloc[-1]
    assert i.prior_high20==101 and i.volume_ratio==2
    a=analyze(f,'2024-12-20');assert a['reasons'][-1]['met']


def test_missing_and_invalid_block_scoring():
    assert analyze(prices(20),'2024-12-20')['score'] is None
    f=prices();f.loc[0,'VOLUME']=-1
    assert analyze(f,'2024-12-20')['status']=='INVALID'


def test_stale_and_unknown_not_confidence():
    a=analyze(prices(),'2026-10-23')
    assert a['status']=='REVIEW' and a['price_unit']=='unverified'
    assert 'probability' not in a


def test_position_budgets_fees_and_lot():
    r=size_position(100000000,21000,19500,25000)
    assert r['shares']%100==0 and r['planned_loss']<=r['risk_budget'] and r['cost']<=r['position_cap']
    assert r['net_rr'] < (25000-21000)/(21000-19500)
    assert size_position(100,21000,19500,25000)['shares']==0


@pytest.mark.parametrize('stop,target',[(22000,25000),(19500,20000),(21000,25000)])
def test_invalid_trade(stop,target):
    with pytest.raises(ValueError):size_position(100000000,21000,stop,target)


def test_endpoints(signed_client,monkeypatch):
    import src.web.app as web
    monkeypatch.setattr(web,'load_market_data',lambda *args:(prices(),{'symbol':args[0]}))
    r=signed_client.get('/api/research/HPG');assert r.status_code==200 and r.json()['score'] is not None
    r=signed_client.post('/api/research-scan',json={'symbols':['HPG','FPT','HPG']});assert len(r.json()['items'])==2
    assert signed_client.post('/api/research-scan',json={'symbols':['HPG']*31}).status_code==422
    assert signed_client.post('/api/position-size',json={'capital':100000000,'entry':21000,'stop':19500,'target':25000}).status_code==200
    assert signed_client.post('/api/position-size',json={'capital':100000000,'entry':21000,'stop':22000,'target':25000}).status_code==422


def test_research_requires_auth(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from src.web.app import app
    monkeypatch.setenv('QTA_AUTH_DB',str(tmp_path/'isolated.db'))
    c=TestClient(app)
    assert c.get('/api/research/HPG').status_code==401
    assert c.post('/api/research-scan',json={'symbols':['HPG']}).status_code==401
    assert c.post('/api/position-size',json={}).status_code==401
