import hashlib
import json
import sqlite3
import pandas as pd
import pytest
from src.data_quality import assess,audit_database,save_report,assert_report_matches

def frame():
    return pd.DataFrame({'TRADE_DATE':['2026-10-19','2026-10-20'],'OPEN_PRICE':[10,10],
        'HIGH_PRICE':[11,11],'LOW_PRICE':[9,9],'CLOSE_PRICE':[10,10],'VOLUME':[100,100],
        'SOURCE':['demo','demo'],'QUALITY_STATUS':['VALID','VALID'],'ADJ_CLOSE':[10,10]})

def test_empty_and_not_certified():
    assert assess(pd.DataFrame(),'2026-10-22')['status']=='NO_DATA'
    d=assess(frame(),'2026-10-22')
    assert d['status']=='CHECKS_PASSED_NOT_VERIFIED'
    assert d['price_basis']=='unknown'

@pytest.mark.parametrize('kind',['geometry','negative','nan','duplicate','future','invalid_date'])
def test_invalid(kind):
    f=frame()
    if kind=='geometry':f.loc[0,'HIGH_PRICE']=5
    if kind=='negative':f.loc[0,'VOLUME']=-1
    if kind=='nan':f.loc[0,'CLOSE_PRICE']=float('nan')
    if kind=='duplicate':f.loc[1,'TRADE_DATE']=f.loc[0,'TRADE_DATE']
    if kind=='future':f.loc[1,'TRADE_DATE']='2026-10-25'
    if kind=='invalid_date':f.loc[0,'TRADE_DATE']='bad'
    assert assess(f,'2026-10-22')['status']=='INVALID'

def test_warning_is_not_rejection_or_certification():
    f=frame();f.loc[0,'QUALITY_STATUS']='UNVERIFIED_ADJ_CLOSE';f.loc[1,'VOLUME']=0
    a=assess(f,'2026-10-22')
    assert a['status']=='REVIEW' and a['unverified_rows']==1 and a['zero_volume']==1
    assert a['adj_close_missing']==0

def test_move_and_stale_are_review_only():
    f=frame();f.loc[1,['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE']]=[15,16,14,15]
    a=assess(f,'2026-10-26')
    assert a['status']=='REVIEW' and a['large_moves']==1 and a['elapsed_weekdays']==3

@pytest.fixture
def db_file(tmp_path):
    p=tmp_path/'test.db'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE STOCK_SYMBOLS(SYMBOL TEXT,EXCHANGE TEXT)')
        c.executemany('INSERT INTO STOCK_SYMBOLS VALUES(?,?)',[('AAA','HOSE'),('BBB','HNX')])
        f=frame();f['SYMBOL']='AAA';f.to_sql('STOCK_PRICES',c,index=False)
    return p

def test_audit_read_only_includes_missing(db_file,tmp_path):
    before=hashlib.sha256(db_file.read_bytes()).hexdigest()
    report=audit_database(db_file,'2026-10-22')
    assert report['universe_count']==2 and report['symbols_with_prices']==1
    assert report['status_counts']['NO_DATA']==1
    assert hashlib.sha256(db_file.read_bytes()).hexdigest()==before
    save_report(report,tmp_path/'report.json');assert (tmp_path/'report.csv').exists()
    assert_report_matches(report,db_file)
    with sqlite3.connect(db_file) as c:c.execute('UPDATE STOCK_PRICES SET VOLUME=0')
    with pytest.raises(ValueError):assert_report_matches(report,db_file)

def test_missing_db_does_not_create(tmp_path):
    p=tmp_path/'absent.db'
    with pytest.raises(FileNotFoundError):audit_database(p,'2026-10-22')
    assert not p.exists()

def test_report_endpoint(signed_client,db_file,monkeypatch,tmp_path):
    import src.web.app as web
    from types import SimpleNamespace
    monkeypatch.setattr(web,'get_repo',lambda:SimpleNamespace(db_path=str(db_file)))
    monkeypatch.setattr(web.settings,'reports_dir',tmp_path)
    assert signed_client.get('/api/data-quality').status_code==404
    save_report(audit_database(db_file,'2026-10-22'),tmp_path/'data_quality.json')
    assert signed_client.get('/api/data-quality').status_code==200
    with sqlite3.connect(db_file) as c:c.execute('UPDATE STOCK_PRICES SET VOLUME=0')
    assert signed_client.get('/api/data-quality').status_code==409
