import sqlite3
import pytest
from src.discovery import rank_catalog,RevisionCache,db_revision,read_catalog

ROWS=[{'symbol':'HPG','company_name':'Tập đoàn Hòa Phát','exchange':'HOSE','bars_count':100},
      {'symbol':'ABC','company_name':'Dịch vụ HPG','exchange':'HNX','bars_count':0},
      {'symbol':'HPA','company_name':'Hòa Phát khác','exchange':'UPCOM','bars_count':3}]

def test_exact_symbol_before_company_and_prefix():
    assert rank_catalog(ROWS,' hpg ')['items'][0]['symbol']=='HPG'
    assert {x['symbol'] for x in rank_catalog(ROWS,'hoa phat')['items']}=={'HPG','HPA'}
    assert rank_catalog(ROWS,'hòa phát','HOSE')['items'][0]['symbol']=='HPG'
    assert rank_catalog(ROWS,'','HNX',True)['items']==[]
    assert rank_catalog(ROWS,'qwerty')['total']==0
    assert rank_catalog(ROWS,'',limit=1)['total']==3

def test_cache_is_bounded_and_copies_values(monkeypatch):
    import src.discovery as d
    clock=[0];monkeypatch.setattr(d.time,'monotonic',lambda:clock[0])
    c=RevisionCache(maxsize=2,ttl=10);c.put('a',{'x':[1]});c.get('a')['x'].append(2)
    assert c.get('a')=={'x':[1]}
    c.put('b',{});c.put('c',{});assert c.get('a') is None
    clock[0]=11;assert c.get('c') is None

def test_revision_and_wal(tmp_path):
    p=tmp_path/'data.db';p.write_bytes(b'a');before=db_revision(p)
    p.write_bytes(b'b');assert db_revision(p)!=before
    wal=tmp_path/'data.db-wal';wal.write_bytes(b'x');assert db_revision(p) is None

def test_catalog_keeps_no_price_and_orphans(tmp_path):
    p=tmp_path/'data.db'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE STOCK_SYMBOLS(SYMBOL TEXT,COMPANY_NAME TEXT,EXCHANGE TEXT)')
        c.execute("INSERT INTO STOCK_SYMBOLS VALUES('AAA','Doanh nghiệp A','HOSE')")
        c.execute('CREATE TABLE STOCK_PRICES(SYMBOL TEXT,TRADE_DATE TEXT)')
        c.execute("INSERT INTO STOCK_PRICES VALUES('BBB','2026-01-01')")
    rows=read_catalog(p);assert len(rows)==2
    assert rows[0]['bars_count']==0 and rows[1]['exchange']=='UNKNOWN'
    with sqlite3.connect(p) as c:c.execute("INSERT INTO STOCK_PRICES VALUES('AAA','2026-01-02')")
    assert read_catalog(p)[0]['bars_count']==1

def test_search_endpoint_validation(signed_client,monkeypatch):
    import src.web.app as web
    monkeypatch.setattr(web,'read_catalog',lambda *a:ROWS)
    assert signed_client.get('/api/catalog-search?q=hoa%20phat').json()['total']==2
    assert signed_client.get('/api/catalog-search?limit=101').status_code==422
    assert signed_client.get('/api/catalog-search?exchange=INVALID').status_code==422


def test_research_cache_invalidates_on_db_change(signed_client,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from tests.test_research import prices
    import src.web.app as web
    p=tmp_path/'revision.db';p.write_bytes(b'first')
    monkeypatch.setattr(web,'get_repo',lambda:SimpleNamespace(db_path=str(p)))
    calls=[]
    def loader(*args):
        calls.append(args[0]);return prices(),{'symbol':args[0]}
    monkeypatch.setattr(web,'load_market_data',loader)
    first=signed_client.get('/api/research/HPG').json()
    second=signed_client.get('/api/research/hpg').json()
    assert not first['cache_hit'] and second['cache_hit'] and len(calls)==1
    assert first['indicators']==second['indicators']
    p.write_bytes(b'changed')
    assert not signed_client.get('/api/research/HPG').json()['cache_hit']
    assert len(calls)==2
