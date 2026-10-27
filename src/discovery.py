"""Deterministic catalog lookup and revision-aware bounded cache."""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock
import time
import unicodedata
import sqlite3


def normalize(text):
    text=str(text or '').casefold().replace('đ','d')
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD',text) if not unicodedata.combining(c)).split())


def rank_catalog(items, query='', exchange='', has_data=False, limit=20):
    q=normalize(query);tokens=q.split();found=[]
    for item in items:
        if exchange and item['exchange'].upper()!=exchange.upper():continue
        if has_data and not item['bars_count']:continue
        symbol=normalize(item['symbol']);name=normalize(item['company_name'])
        if not q:rank=4;match='Danh mục'
        elif symbol==q:rank=0;match='Khớp chính xác mã'
        elif symbol.startswith(q):rank=1;match='Khớp đầu mã'
        elif q in name:rank=2;match='Khớp tên doanh nghiệp'
        elif all(t in symbol+' '+name for t in tokens):rank=3;match='Khớp các từ tìm kiếm'
        else:continue
        found.append((rank,item['symbol'],{**item,'match_reason':match}))
    found.sort(key=lambda x:(x[0],x[1]))
    return {'total':len(found),'items':[x[2] for x in found[:limit]]}


def db_revision(path):
    if not path:return None
    p=Path(path).resolve()
    try:
        for suffix in ('-wal','-journal'):
            side=Path(str(p)+suffix)
            if side.exists() and side.stat().st_size:return None
        s=p.stat()
        return (str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    except OSError:return None


class RevisionCache:
    def __init__(self,maxsize=512,ttl=120):
        self.maxsize=maxsize;self.ttl=ttl;self.items=OrderedDict();self.lock=RLock()
    def get(self,key):
        if key is None:return None
        with self.lock:
            entry=self.items.get(key)
            if entry is None:return None
            if time.monotonic()-entry[0]>self.ttl:
                del self.items[key];return None
            self.items.move_to_end(key)
            return deepcopy(entry[1])
    def put(self,key,value):
        if key is None:return
        with self.lock:
            self.items[key]=(time.monotonic(),deepcopy(value));self.items.move_to_end(key)
            while len(self.items)>self.maxsize:self.items.popitem(last=False)


catalog_cache=RevisionCache(maxsize=4,ttl=60)
research_cache=RevisionCache()


def read_catalog(db_path):
    revision=db_revision(db_path)
    cached=catalog_cache.get(revision)
    if cached is not None:return cached
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''WITH p AS (
            SELECT SYMBOL,COUNT(*) AS bars_count,MAX(TRADE_DATE) AS last_date FROM STOCK_PRICES GROUP BY SYMBOL
        ), u AS (SELECT SYMBOL FROM STOCK_SYMBOLS UNION SELECT SYMBOL FROM p)
        SELECT u.SYMBOL AS symbol,COALESCE(s.COMPANY_NAME,u.SYMBOL) AS company_name,
               COALESCE(s.EXCHANGE,'UNKNOWN') AS exchange,COALESCE(p.bars_count,0) AS bars_count,
               p.last_date AS last_date
        FROM u LEFT JOIN STOCK_SYMBOLS s ON s.SYMBOL=u.SYMBOL LEFT JOIN p ON p.SYMBOL=u.SYMBOL
        ORDER BY u.SYMBOL''').fetchall()
        result=[dict(r) for r in rows]
    if revision==db_revision(db_path):catalog_cache.put(revision,result)
    return result
