"""Owner-scoped personal data; separate database, never migrates the price database."""
import os,json,sqlite3
from pathlib import Path
from src.config import settings

def connect():
    p=Path(os.getenv('QTA_USER_DB',str(settings.state_dir/'qta_phase7_users.db')));p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(p);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS watch(owner TEXT,symbol TEXT,state TEXT,PRIMARY KEY(owner,symbol));
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,owner TEXT,symbol TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,before_state TEXT,after_state TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY,owner TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS filters(owner TEXT PRIMARY KEY,payload TEXT);''');return db

def watches(owner):
    with connect() as db:return [dict(r) for r in db.execute('SELECT symbol,state FROM watch WHERE owner=? ORDER BY symbol',(owner,))]
def watch(owner,symbol,remove=False):
    with connect() as db:
        if remove:db.execute('DELETE FROM watch WHERE owner=? AND symbol=?',(owner,symbol))
        else:db.execute('INSERT OR IGNORE INTO watch(owner,symbol) VALUES(?,?)',(owner,symbol))
def poll(owner,states):
    with connect() as db:
        for row in db.execute('SELECT * FROM watch WHERE owner=?',(owner,)).fetchall():
            if row['symbol'] not in states:continue
            state=json.dumps(states[row['symbol']],sort_keys=True)
            if row['state'] is not None and state!=row['state']:db.execute('INSERT INTO alerts(owner,symbol,before_state,after_state) VALUES(?,?,?,?)',(owner,row['symbol'],row['state'],state))
            db.execute('UPDATE watch SET state=? WHERE owner=? AND symbol=?',(state,owner,row['symbol']))
        return [dict(r) for r in db.execute('SELECT * FROM alerts WHERE owner=? ORDER BY id DESC LIMIT 100',(owner,))]
def journal(owner,payload=None):
    with connect() as db:
        if payload is not None:db.execute('INSERT INTO journal(owner,payload) VALUES(?,?)',(owner,json.dumps(payload,ensure_ascii=False)))
        return [{'id':r['id'],**json.loads(r['payload'])} for r in db.execute('SELECT * FROM journal WHERE owner=? ORDER BY id DESC',(owner,))]
def filters(owner,payload=None):
    with connect() as db:
        if payload is not None:db.execute('INSERT OR REPLACE INTO filters VALUES(?,?)',(owner,json.dumps(payload)))
        row=db.execute('SELECT payload FROM filters WHERE owner=?',(owner,)).fetchone();return json.loads(row[0]) if row else {}
