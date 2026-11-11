"""Independent specifications and prefix invariance; synthetic candles are test fixtures only."""
import sys,subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from swing_detector import SwingDetectorConfig as C,detect_result,detect_swings_frame,compute_wilder_atr,clean_data
from swing_detector.detector import left_qualified,pivot_qualified,COLUMNS
from swing_detector.io import export_result


def candles(n=180):
    times=[]
    for d in pd.date_range('2025-01-02',periods=40,freq='B'):
        for a,b in [('09:00','11:15'),('13:00','14:45')]:
            times.extend(pd.date_range(str(d.date())+' '+a,str(d.date())+' '+b,freq='15min',tz='Asia/Ho_Chi_Minh'))
    rng=np.random.default_rng(731);c=100+8*np.sin(np.arange(n)*.36)+np.cumsum(rng.normal(0,.3,n))
    return pd.DataFrame({'Datetime':times[:n],'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':np.arange(n)+100})


def test_clean_reports_all_bad_rows(caplog):
    d=candles(30);d['Datetime']=d.Datetime.astype(object);d.loc[0,'High']=0;d.loc[1,'Volume']=-1;d.loc[2,'Close']=np.nan
    d.loc[3,'Datetime']='bad';d.loc[4,'Datetime']=pd.Timestamp('2025-01-02 12:00',tz='Asia/Ho_Chi_Minh')
    d.loc[5,'Datetime']=pd.Timestamp('2025-01-02 10:16',tz='Asia/Ho_Chi_Minh')
    d=pd.concat([d,d.iloc[[10]]],ignore_index=True).iloc[::-1]
    out,a=clean_data(d)
    assert len(out)==24 and a['removed_rows']==7
    assert set(a['removal_counts'])=={'nonpositive_price','negative_volume','missing_or_nonfinite','invalid_datetime','outside_session','off_15m_grid','duplicate_datetime'}
    assert out.Datetime.is_monotonic_increasing and out.Datetime.is_unique
    assert 'Removed 7' in caplog.text

@pytest.mark.parametrize('col',['Datetime','Open','High','Low','Close','Volume'])
def test_required_columns(col):
    with pytest.raises(ValueError):clean_data(candles().drop(columns=col))

def test_geometry_zero_volume_and_missing_grid():
    d=candles(30);d.loc[0,'High']=d.loc[0,'Close']-.1;d.loc[1,'Volume']=0
    out,a=clean_data(d.drop(index=8))
    assert a['removal_counts']=={'invalid_ohlc':1};assert a['zero_volume_rows']==1
    assert a['potential_missing_bars']==1

def test_timezone_and_cutoff():
    d=candles(30);utc=d.copy();utc.Datetime=utc.Datetime.dt.tz_convert('UTC')
    pd.testing.assert_frame_equal(clean_data(d)[0],clean_data(utc)[0])
    cutoff=d.Datetime.iloc[10]
    assert len(clean_data(d,as_of=cutoff)[0])==10
    assert len(clean_data(d,C(timestamp_label='close'),as_of=cutoff)[0])<=11

def test_first_valid_duplicate_wins():
    d=candles(3);bad=d.iloc[[0]].copy();bad.High=-1
    out,a=clean_data(pd.concat([bad,d],ignore_index=True))
    assert len(out)==3;assert out.High.iloc[0]==d.High.iloc[0]

def test_wilder_hand_values():
    # TR = 2,3,4,5 => first ATR3=3, next=(2*3+5)/3=11/3.
    d=pd.DataFrame({'High':[11,12,13,14],'Low':[9,9,9,9],'Close':[10]*4})
    a=compute_wilder_atr(d,3)
    np.testing.assert_allclose(a,[np.nan,np.nan,3,11/3],equal_nan=True)
    assert np.isnan(compute_wilder_atr(d,14)).all()

def test_wilder_14_seed_and_recurrence():
    d=pd.DataFrame({'High':np.arange(1,17)+100.,'Low':np.full(16,100.),'Close':np.full(16,100.)})
    a=compute_wilder_atr(d)
    assert np.isnan(a[:13]).all();assert a[13]==7.5
    assert a[14]==(13*7.5+15)/14;assert a[15]==(13*a[14]+16)/14

def test_missing_atr_is_rejected():
    d=candles(20);d.loc[1,'High']=np.nan
    with pytest.raises(ValueError):compute_wilder_atr(d)

@pytest.mark.parametrize('kind,mult',[('HIGH',1),('LOW',-1)])
def test_pivot_tie_and_availability(kind,mult):
    x=mult*np.array([1.,2,3,5,5,4,2,1])
    assert left_qualified(x,3,3,kind)
    assert not pivot_qualified(x,3,5,3,3,kind)
    assert pivot_qualified(x,3,6,3,3,kind)
    assert not left_qualified(x,4,3,kind)

def test_threshold_frozen_and_volume_definition():
    r=detect_result(candles());assert len(r.swings)>5
    for row,(i,t) in zip(r.swings.to_dict('records'),r.indices):
        assert row['threshold_T']==max(2*r.candles.ATR.iloc[i],.005*row['extreme_price'])
        assert row['atr_at_extreme']==r.candles.ATR.iloc[i]
        assert row['confirmed_at']==r.candles.available_time.iloc[t]
        assert row['reversal_size_in_ATR']>=row['threshold_T']/row['atr_at_extreme']-1e-10
        if i>=20:
            assert row['volume_ratio']==pytest.approx(r.candles.Volume.iloc[i+1:t+1].sum()/r.candles.Volume.iloc[i-20:i].median())
        else:assert np.isnan(row['volume_ratio'])

def test_alternation_spacing_all_are_pivots():
    r=detect_result(candles(300));assert len(r.swings)>10
    assert (r.swings.swing_type.iloc[1:].to_numpy()!=r.swings.swing_type.iloc[:-1].to_numpy()).all()
    for row,(i,t) in zip(r.swings.to_dict('records'),r.indices):
        v=r.candles.High.to_numpy() if row['swing_type']=='HIGH' else r.candles.Low.to_numpy()
        assert pivot_qualified(v,i,t,3,3,row['swing_type'])
    assert r.swings.bars_since_prev_swing.iloc[1:].tolist()==np.diff([i for i,t in r.indices]).tolist()
    r=detect_result(candles(300),C(min_bars_between_swings=20))
    assert (r.swings.bars_since_prev_swing.dropna()>=20).all()

def test_ambiguous_outside_bar_deferred():
    d=candles(100)
    # Make every tenth bar a large outside bar; real decisions must defer there.
    for i in range(20,100,10):d.loc[i,['High','Low']]=[140,60]
    r=detect_result(d,C(reversal_atr_mult=1.5))
    deferred={e['bar'] for e in r.events if e['reason']=='ambiguous_defer'}
    assert deferred
    assert not deferred.intersection(t for i,t in r.indices)

@pytest.mark.parametrize('k',[1.5,2.,2.5])
@pytest.mark.parametrize('pivot',[3,5])
def test_no_lookahead_every_prefix(k,pivot):
    d=candles(110);cfg=C(reversal_atr_mult=k,pivot_left=pivot,pivot_right=pivot)
    full=detect_swings_frame(d,cfg)
    for n in range(1,len(d)+1):
        actual=detect_swings_frame(d.iloc[:n],cfg)
        expected=full[full.confirmed_at<=d.Datetime.iloc[n-1]+pd.Timedelta(minutes=15)].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual,expected,check_dtype=False)

def test_empty_and_flat_no_division_by_zero():
    d=candles(30);d[['Open','High','Low','Close']]=100;d.Volume=0
    assert detect_swings_frame(d).empty
    assert list(detect_swings_frame(d.iloc[:0]))==COLUMNS

def test_legacy_csv_layer2_compatibility(tmp_path):
    from common.io import load_swings
    from structure_builder import MarketStructureBuilder
    r=detect_result(candles());path=tmp_path/'swings.csv';export_result(r,path)
    s=load_swings(path);assert len(s)==len(r.swings)
    MarketStructureBuilder().build_from_file(path)
    assert {'swing_type','confirmed_at','threshold_T'}.issubset(pd.read_csv(path).columns)

def test_core_does_not_import_layer2_or_common():
    subprocess.run([sys.executable,'-c',"import swing_detector,sys; assert 'structure_builder' not in sys.modules; assert 'common.models' not in sys.modules"],check=True)

@pytest.mark.parametrize('kw',[{'pivot_left':0},{'reversal_atr_mult':float('nan')},{'tie_rule':'last'},{'min_bars_between_swings':-1}])
def test_invalid_config(kw):
    with pytest.raises(ValueError):C(**kw)

def test_higher_candidate_replaces_and_freezes_new_threshold():
    r=detect_result(candles(100))
    events=[e for e in r.events if e['reason']=='candidate']
    assert len(events)>len(r.swings)
    for e in events:
        i=e['extreme_index'];price=r.candles.High.iloc[i] if e['type']=='HIGH' else r.candles.Low.iloc[i]
        assert e['threshold_T']==max(2*r.candles.ATR.iloc[i],.005*price)
    for i,t in r.indices:
        matched=[e for e in events if e['extreme_index']==i]
        assert matched

def test_ambiguous_init_both_eligible_is_deferred():
    # Search deterministic fixtures with small threshold; no inferred intrabar order.
    cfg=C(atr_period=1,pivot_left=1,pivot_right=1,reversal_atr_mult=.1,reversal_min_pct=0)
    d=candles(12)
    d[['Open','Close']]=100.;d.High=[101,105,103,102,104,103,102,101,103,102,101,102]
    d.Low=[99,95,97,97,96,97,98,99,98,99,99,99]
    r=detect_result(d,cfg)
    both=[e for e in r.events if e['reason']=='ambiguous_defer' and len(e['eligible'])==2]
    assert both
    assert not {e['bar'] for e in both}.intersection(t for i,t in r.indices)

def test_volume_never_filters_swings():
    d=candles();a=detect_swings_frame(d);d.Volume=0;b=detect_swings_frame(d)
    pd.testing.assert_frame_equal(a.drop(columns='volume_ratio'),b.drop(columns='volume_ratio'))
    assert b.volume_ratio.isna().all()

@pytest.mark.parametrize('suffix',['.csv','.json'])
def test_canonical_schema_and_metadata(tmp_path,suffix):
    import json
    from swing_detector import detect_swings,save_swings
    from common.io import load_swings
    from structure_builder import MarketStructureBuilder
    cfg=C(ticker=' hpg ');r=detect_result(candles(),cfg)
    required=['swing_id','ticker','timeframe','swing_type','extreme_price','extreme_time',
              'confirmed_at','atr_at_extreme','source_version','rule_version']
    assert list(r.swings.columns[:10])==required
    assert r.swings.swing_id.is_unique and r.swings.swing_id.notna().all()
    assert set(r.swings.ticker)=={'HPG'} and set(r.swings.timeframe)=={'15m'}
    assert not {'type','price','confirm_time','atr_at_candidate'}.intersection(r.swings.columns)
    path=tmp_path/('swings'+suffix);save_swings(detect_swings(candles(),cfg),path)
    frame=pd.read_csv(path) if suffix=='.csv' else pd.DataFrame(json.loads(path.read_text()))
    assert set(required).issubset(frame.columns)
    assert set(frame.ticker)=={'HPG'} and frame.source_version.notna().all()
    loaded=load_swings(path);assert len(loaded)==len(r.swings)
    builder=MarketStructureBuilder();sw,_=builder.build_from_file(path,as_of_time=loaded[0].confirmed_at)
    assert len(sw)==1

@pytest.mark.parametrize('suffix',['.csv','.json'])
def test_invalid_atr_exports_null(tmp_path,suffix):
    import json
    r=detect_result(candles(),C(ticker='HPG'));r.swings.loc[0,'atr_at_extreme']=np.nan
    path=tmp_path/('swings'+suffix);export_result(r,path)
    if suffix=='.json':assert json.loads(path.read_text())[0]['atr_at_extreme'] is None
    else:assert pd.isna(pd.read_csv(path).atr_at_extreme.iloc[0])

def test_duplicate_ids_rejected_on_export(tmp_path):
    r=detect_result(candles());r.swings.loc[1,'swing_id']=r.swings.loc[0,'swing_id']
    with pytest.raises(ValueError,match='unique'):export_result(r,tmp_path/'bad.csv')

def test_empty_export_keeps_canonical_header(tmp_path):
    r=detect_result(candles(3),C(ticker='HPG'));path=tmp_path/'empty.csv';export_result(r,path)
    assert pd.read_csv(path).empty
    assert set(COLUMNS).issubset(pd.read_csv(path).columns)
