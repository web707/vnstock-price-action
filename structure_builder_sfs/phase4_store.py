"""Separate, immutable, versioned classification/context snapshots in SQLite."""
import sqlite3
from .phase4 import ContextRules,canonical

class ContextStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS phase4_rule_version (rule_version TEXT PRIMARY KEY, config_hash TEXT NOT NULL, config_json TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS phase4_snapshot (snapshot_id TEXT PRIMARY KEY,rule_version TEXT,ticker TEXT,timeframe TEXT,source_version TEXT,as_of_time TEXT,payload_json TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS classified_structure_snapshot (snapshot_id TEXT,structure_id TEXT,classification TEXT,status TEXT,rule_version TEXT,payload_json TEXT NOT NULL,PRIMARY KEY(snapshot_id,structure_id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS major_structure_sequence (snapshot_id TEXT,structure_id TEXT,structure_sequence_no INTEGER,previous_major_structure_id TEXT,structure_direction TEXT,status TEXT,confirmed_at TEXT,rule_version TEXT,PRIMARY KEY(snapshot_id,structure_id),UNIQUE(snapshot_id,structure_sequence_no))')
        self.db.execute('CREATE TABLE IF NOT EXISTS structure_context_snapshot (context_id TEXT PRIMARY KEY,snapshot_id TEXT,ticker TEXT,timeframe TEXT,source_version TEXT,as_of_time TEXT,query_mode TEXT,older_structure_id TEXT,latest_structure_id TEXT,context_status TEXT,is_long_candidate INTEGER,reason_code TEXT,rule_version TEXT,payload_json TEXT NOT NULL)')
    def close(self):self.db.close()
    def save(self,snapshot,contexts):
        p=ContextRules(snapshot['rule_config'])
        if p.version!=snapshot['rule_version'] or p.config_hash!=snapshot['config_hash']:raise ValueError('SNAPSHOT_RULE_MISMATCH')
        with self.db:
            old=self.db.execute('SELECT config_hash FROM phase4_rule_version WHERE rule_version=?',(p.version,)).fetchone()
            if old and old[0]!=p.config_hash:raise ValueError('RULE_VERSION_CONFIG_CONFLICT')
            self.db.execute('INSERT OR IGNORE INTO phase4_rule_version VALUES (?,?,?)',(p.version,p.config_hash,canonical(p.as_dict())))
            payload=canonical(snapshot);sid=snapshot['snapshot_id']
            old=self.db.execute('SELECT payload_json FROM phase4_snapshot WHERE snapshot_id=?',(sid,)).fetchone()
            if old and old[0]!=payload:raise ValueError('IMMUTABLE_SNAPSHOT_CONFLICT')
            if not old:
                self.db.execute('INSERT INTO phase4_snapshot VALUES (?,?,?,?,?,?,?)',(sid,p.version,snapshot['ticker'],snapshot['timeframe'],snapshot['source_version'],snapshot['as_of_time'].isoformat(),payload))
                for r in snapshot['classified_structures']:
                    self.db.execute('INSERT INTO classified_structure_snapshot VALUES (?,?,?,?,?,?)',(sid,r['structure_id'],r['classification'],r['status'],p.version,canonical(r)))
                for r in snapshot['major_sequence']:
                    self.db.execute('INSERT INTO major_structure_sequence VALUES (?,?,?,?,?,?,?,?)',(sid,r['structure_id'],r['structure_sequence_no'],r['previous_major_structure_id'],r['structure_direction'],r['status'],r['confirmed_at'].isoformat(),p.version))
            for c in contexts:
                if c['snapshot_id']!=sid or c['rule_version']!=p.version or c['config_hash']!=p.config_hash:raise ValueError('CONTEXT_SNAPSHOT_MISMATCH')
                if c['query_mode'] not in p.get('query_modes') or c['is_long_candidate'] is not None or c['reason_code']!=p.get('long_reason'):raise ValueError('INVALID_CONTEXT_POLICY')
                payload=canonical(c);old=self.db.execute('SELECT payload_json FROM structure_context_snapshot WHERE context_id=?',(c['context_id'],)).fetchone()
                if old and old[0]!=payload:raise ValueError('IMMUTABLE_CONTEXT_CONFLICT')
                if not old:self.db.execute('INSERT INTO structure_context_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(c['context_id'],sid,c['ticker'],c['timeframe'],c['source_version'],c['as_of_time'].isoformat(),c['query_mode'],c['older_structure_id'],c['latest_structure_id'],c['context_status'],None,c['reason_code'],p.version,payload))
