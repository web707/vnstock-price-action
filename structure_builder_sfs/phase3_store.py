"""Separate SQLite event store. Immutable events and version/config collision guards."""
import json, sqlite3
import pandas as pd
from .phase3 import STRUCTURE_COLUMNS, EVENT_COLUMNS, decode_snapshot
from .phase3_rules import RuleProvider

def sql_value(x):
    if x is None:return None
    if isinstance(x,(list,dict)):return json.dumps(x,sort_keys=True,default=str)
    if pd.isna(x):return None
    if isinstance(x,pd.Timestamp):return x.isoformat()
    if isinstance(x,bool):return int(x)
    return x.item() if hasattr(x,'item') else x

class StructureStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path);self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS structure_rule_version (rule_version TEXT PRIMARY KEY, config_hash TEXT NOT NULL, config_json TEXT NOT NULL)')
        numeric={'amplitude','amplitude_atr','atr_reference','atr_multiplier','protected_level','break_level','break_price','rejection_price'}
        integers={'event_sequence','geometry_qualified','amplitude_filter_passed','structure_sequence_no'}
        for table,cols,pk,extra in [('market_structure',STRUCTURE_COLUMNS,'structure_id',''),('market_structure_event',EVENT_COLUMNS,'event_id',', UNIQUE(structure_id,event_sequence)')]:
            definitions=[c+(' REAL' if c in numeric else ' INTEGER' if c in integers else ' TEXT')+(' PRIMARY KEY' if c==pk else '') for c in cols]
            self.db.execute('CREATE TABLE IF NOT EXISTS '+table+' ('+','.join(definitions)+extra+')')
    def close(self):self.db.close()
    def save(self,result):
        p=RuleProvider(result['rule_config'])
        with self.db:
            old=self.db.execute('SELECT config_hash FROM structure_rule_version WHERE rule_version=?',(p.version,)).fetchone()
            if old and old[0]!=p.config_hash:raise ValueError('RULE_VERSION_CONFIG_CONFLICT')
            self.db.execute('INSERT OR IGNORE INTO structure_rule_version VALUES (?,?,?)',(p.version,p.config_hash,json.dumps(p.as_dict(),sort_keys=True)))
            for raw in result['market_structure_event'].to_dict('records'):
                r={k:sql_value(raw[k]) for k in EVENT_COLUMNS}
                old=self.db.execute('SELECT * FROM market_structure_event WHERE structure_id=? AND event_sequence=?',(r['structure_id'],r['event_sequence'])).fetchone()
                if old:
                    if dict(old)!=r:raise ValueError('HISTORICAL_EVENT_CONFLICT')
                    continue
                self.db.execute('INSERT INTO market_structure_event ('+','.join(EVENT_COLUMNS)+') VALUES ('+','.join('?' for _ in EVENT_COLUMNS)+')',list(r.values()))
            for raw in result['market_structure'].to_dict('records'):
                r={k:sql_value(raw[k]) for k in STRUCTURE_COLUMNS}
                old=self.db.execute('SELECT available_at,created_at FROM market_structure WHERE structure_id=?',(r['structure_id'],)).fetchone()
                if old and pd.Timestamp(old[0])>=pd.Timestamp(r['available_at']):continue
                if old:r['created_at']=old[1]
                self.db.execute('INSERT INTO market_structure ('+','.join(STRUCTURE_COLUMNS)+') VALUES ('+','.join('?' for _ in STRUCTURE_COLUMNS)+') ON CONFLICT(structure_id) DO UPDATE SET '+','.join(c+'=excluded.'+c for c in STRUCTURE_COLUMNS if c!='structure_id'),list(r.values()))
    def historical_rows(self,as_of,rule_version):
        t=pd.Timestamp(as_of)
        if t.tzinfo is None:raise ValueError('Timezone required')
        rows={}
        for e in self.db.execute('SELECT * FROM market_structure_event WHERE rule_version=? ORDER BY event_sequence,event_id',(rule_version,)):
            if pd.Timestamp(e['available_at'])<=t:rows[e['structure_id']]=decode_snapshot(e['payload_json'])
        return list(rows.values())
