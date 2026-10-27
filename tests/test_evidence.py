import json
import numpy as np
import pandas as pd
import pytest
from src.evidence import evaluate,summarize
from src.research import analyze,indicators,score_components


def frame(n=650):
    return pd.DataFrame({'TRADE_DATE':pd.bdate_range('2019-01-01',periods=n),
        'OPEN_PRICE':np.full(n,100.),'HIGH_PRICE':np.full(n,102.),'LOW_PRICE':np.full(n,98.),
        'CLOSE_PRICE':np.full(n,100.),'VOLUME':np.full(n,200000),
        'ADJ_CLOSE':np.full(n,100.),'QUALITY_STATUS':'VALID','SOURCE':'test'})


def test_next_open_costs_and_nonoverlap():
    f=frame(230);f.loc[200,'OPEN_PRICE']=101;f.loc[209,'CLOSE_PRICE']=102
    r=evaluate(f,horizon=10,threshold=0,min_volume=0,fee_pct=0,tax_pct=0,slippage_pct=0)
    obs=r['observations'];assert len(obs)==3
    assert obs[0]['entry_date']==str(f.TRADE_DATE.iloc[200])[:10]
    assert obs[0]['exit_date']==str(f.TRADE_DATE.iloc[209])[:10]
    assert obs[0]['net_return_pct']==pytest.approx((102/101-1)*100)
    assert all(a['exit_date']<b['entry_date'] for a,b in zip(obs,obs[1:]))
    assert r['signal']==r['baseline']
    costly=evaluate(f,horizon=10,threshold=0,min_volume=0)
    assert costly['signal']['mean_net_pct']<r['signal']['mean_net_pct']


def test_score_single_source_and_causal():
    f=frame();f['CLOSE_PRICE']+=np.sin(np.arange(len(f))/10)
    scores=score_components(f).sum(axis=1)
    for k in (210,350,649):
        assert scores.iloc[k]==analyze(f.iloc[:k+1])['score']
    pd.testing.assert_frame_equal(score_components(f.iloc[:350]),score_components(f).iloc[:350])


def test_completed_observations_do_not_change_with_future_data():
    f=frame();a=evaluate(f.iloc[:400],threshold=0);b=evaluate(f,threshold=0)
    assert a['observations']==b['observations'][:len(a['observations'])]
    changed=f.copy();changed.loc[400:,'CLOSE_PRICE']=101
    c=evaluate(changed,threshold=0)
    assert a['observations']==c['observations'][:len(a['observations'])]


def test_empty_low_samples_and_exclusions():
    assert evaluate(frame(209))['status']=='INSUFFICIENT_HISTORY'
    r=evaluate(frame(230),threshold=100)
    assert r['status']=='TOO_FEW_SAMPLES' and r['signal']['count']==0
    assert r['signal']['win_rate_pct'] is None
    f=frame(230);f.loc[200,'VOLUME']=0
    r=evaluate(f,threshold=0)
    assert r['excluded']['unavailable_execution_volume']==1
    assert r['scheduled_windows']==len(r['observations'])+sum(r['excluded'].values())
    json.dumps(r,allow_nan=False)


def test_invalid_data_and_parameters():
    f=frame();f.loc[0,'LOW_PRICE']=999
    with pytest.raises(ValueError):evaluate(f)
    with pytest.raises(ValueError):evaluate(frame(),horizon=2)
    with pytest.raises(ValueError):evaluate(frame(),fee_pct=float('nan'))


def test_summary_wilson_and_no_losses():
    assert summarize([])['mean_net_pct'] is None
    s=summarize([.1]*20);assert s['profit_factor'] is None
    assert s['win_interval_pct'][0]<100 and s['win_interval_pct'][1]==100
    s=summarize([.1,-.05]);assert s['profit_factor']==pytest.approx(2)
    assert s['win_interval_pct'][0]<50<s['win_interval_pct'][1]


def test_periods_and_sample_counts():
    r=evaluate(frame(),threshold=0)
    assert len(r['periods'])==4
    assert sum(p['signal']['count'] for p in r['periods'])==r['signal']['count']
    assert r['status']=='NO_OBSERVED_ADVANTAGE'


def test_api_validation_and_auth(signed_client,monkeypatch,tmp_path):
    import src.web.app as web
    from fastapi.testclient import TestClient
    monkeypatch.setattr(web,'load_market_data',lambda *args:(frame(),{'symbol':args[0]}))
    assert signed_client.post('/api/evidence',json={'symbol':'HPG'}).status_code==200
    assert signed_client.post('/api/evidence',json={'symbol':'HPG','horizon':2}).status_code==422
    assert signed_client.post('/api/evidence',json={'symbol':'HPG','fee_pct':-1}).status_code==422
    assert TestClient(web.app).post('/api/evidence',json={'symbol':'HPG'}).status_code==401
