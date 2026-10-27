from datetime import datetime, date
from zoneinfo import ZoneInfo
import sqlite3
import pandas as pd
from phase3_recover import normalize_vnstock, inspect_symbol, is_closed


def test_scaling_and_schema():
    d = pd.DataFrame([{'time':'2026-10-19','open':20,'high':22,'low':19,'close':21,'volume':123}, {'time':'2026-10-20','open':20,'high':19,'low':18,'close':21,'volume':123}])
    result = normalize_vnstock(d)
    assert len(result)==1
    assert result.iloc[0].close==21000


def test_skip_forming_and_preserve_overlap():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE STOCK_PRICES(SYMBOL TEXT, TRADE_DATE TEXT, CLOSE_PRICE REAL)')
        conn.execute('INSERT INTO STOCK_PRICES VALUES (?,?,?)', ('HPG','2026-10-19',22000))
        df=normalize_vnstock(pd.DataFrame([{'time':'2026-10-19','open':20,'high':22,'low':19,'close':21,'volume':10},{'time':'2026-10-21','open':20,'high':22,'low':19,'close':21,'volume':10}]))
        rows, conflicts, overlap, forming=inspect_symbol(conn,'HPG','HOSE','VCI',df,datetime(2026,10,21,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')))
        assert not rows and overlap==1 and forming==1 and len(conflicts)==1


def test_prior_day_closed():
    now=datetime(2026,10,21,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    assert is_closed(date(2026,10,20),now)
    assert not is_closed(date(2026,10,21),now)


def test_unverified_adjusted_close_is_null():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE STOCK_PRICES(SYMBOL TEXT, TRADE_DATE TEXT, CLOSE_PRICE REAL)')
        df=normalize_vnstock(pd.DataFrame([{'time':'2026-10-20','open':20,'high':22,'low':19,'close':21,'volume':10}]))
        rows, _, _, _=inspect_symbol(conn,'AAV','HNX','VCI',df,datetime(2026,10,21,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')))
        assert len(rows)==1 and rows[0][6] is None
