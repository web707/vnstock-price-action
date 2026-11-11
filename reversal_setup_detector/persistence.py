"""Phase4 deterministic, transactional SQLite setup/event sink and LONG_SETUP projection.

No writes to the upstream Layer1/2 database. The immutable natural key is the
spec section 8 five-part key; an exact SQL UNIQUE constraint and PK enforce it.
RECOMPUTED/corrections are rejected if payload diverges under the same version:
callers must use a new rule/source revision instead of silently overwriting.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
import json,sqlite3

SQL_PATH=Path(__file__).parent/'sql/001_reversal_setup.sql'
IMMUTABLE=('ticker','timeframe','rule_version','config_hash','source_version',
           'calendar_id','calendar_hash','calendar_verified','calendar_source_verification',
           'context_structure_id_1','context_structure_id_2','context_available_at',
           'context_age_bars','context_age_coverage_complete',
           'red_candle_1_time','red_candle_1_open','red_candle_1_high','red_candle_1_low','red_candle_1_close',
           'red_candle_2_time','red_candle_2_open','red_candle_2_high','red_candle_2_low','red_candle_2_close',
           'red_candle_3_time','red_candle_3_open','red_candle_3_high','red_candle_3_low','red_candle_3_close',
           'body_1','total_wick_1','body_3','total_wick_3','setup_detected_at',
           'red_triplet_crosses_session','window_crosses_session')
MUTABLE=('status','reversal_candle_time','reversal_candle_open','reversal_candle_high',
         'reversal_candle_low','reversal_candle_close','reversal_body','body_ratio',
         'available_at','resolved_at','reason_code','observed_window_crosses_session')
NOW=lambda:datetime.now(timezone.utc).isoformat()

def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 5000')
    conn.execute('PRAGMA journal_mode = DELETE')
    conn.executescript(SQL_PATH.read_text(encoding='utf-8'))
    return conn

def canonical_json(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def setup_fields(s):
    if len(s['context_structure_ids'])!=2 or len(s['red_candles'])!=3:
        raise ValueError('INCOMPLETE_SETUP_TRACE')
    row=dict(setup_id=s['setup_id'],ticker=s['ticker'],timeframe=s['timeframe'],
             rule_version=s['rule_version'],config_hash=s['config_hash'],source_version=s['source_version'],
             calendar_id=s['calendar_id'],calendar_hash=s['calendar_hash'],
             calendar_verified=int(s['calendar_verified']),
             calendar_source_verification='VERIFIED' if s['calendar_verified'] else 'UNVERIFIED',
             context_structure_id_1=s['context_structure_ids'][0],context_structure_id_2=s['context_structure_ids'][1],
             context_available_at=s['context_available_at'],context_age_bars=s['context_age_bars'],
             context_age_coverage_complete=int(s['context_age_coverage_complete']),
             body_1=s['body_1'],total_wick_1=s['total_wick_1'],
             body_3=s['body_3'],total_wick_3=s['total_wick_3'],
             status=s['status'],reversal_candle_time=s['reversal_candle_time'],
             reversal_body=s['reversal_body'],body_ratio=s['body_ratio'],
             setup_detected_at=s['setup_detected_at'],available_at=s['available_at'],
             resolved_at=s['resolved_at'],reason_code=s['reason_code'],
             red_triplet_crosses_session=int(s['red_triplet_crosses_session']),
             window_crosses_session=int(s['window_crosses_session']),
             observed_window_crosses_session=int(s['observed_window_crosses_session']))
    for n,c in enumerate(s['red_candles'],1):
        row[f'red_candle_{n}_time']=s['red_candle_times'][n-1]
        for field in ('open','high','low','close'):row[f'red_candle_{n}_{field}']=str(c[field])
    g=s['reversal_candle']
    for field in ('open','high','low','close'):
        row[f'reversal_candle_{field}']=str(g[field]) if g is not None else None
    return row

def persist_batch(conn,results,*,expected_rule_version='L3_REVERSAL_V1'):
    """Atomic idempotent persist of one or more point-in-time scan results.

    Existing terminal states are immutable. Earlier prefix replays cannot
    downgrade persisted status, while WAITING -> terminal is allowed.
    Repeated same replay returns zero inserts and zero updates.
    """
    results=list(results)
    if not results:return dict(inserted=0,updated=0,duplicates_prevented=0,events_inserted=0,events_duplicates=0,actions=[])
    version=results[0]['rule_version'];chash=results[0]['config_hash']
    if version!=expected_rule_version or any(x['rule_version']!=version or x['config_hash']!=chash for x in results):
        raise ValueError('RULE_VERSION_OR_HASH_MISMATCH')
    counts=dict(inserted=0,updated=0,duplicates_prevented=0,events_inserted=0,events_duplicates=0,actions=[])
    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
    try:
        collision=cur.execute('SELECT config_hash FROM reversal_setup WHERE rule_version=? AND config_hash<>? LIMIT 1',(version,chash)).fetchone()
        if collision:raise ValueError('RULE_VERSION_CONFIG_HASH_COLLISION')
        now=NOW();newids=set()
        for result in results:
            for s in result['candidates']:
                f=setup_fields(s)
                row=cur.execute('SELECT * FROM reversal_setup WHERE setup_id=?',(f['setup_id'],)).fetchone()
                natural=cur.execute('SELECT setup_id FROM reversal_setup WHERE ticker=? AND timeframe=? AND red_candle_1_time=? AND red_candle_2_time=? AND red_candle_3_time=? AND rule_version=?',
                    (f['ticker'],f['timeframe'],f['red_candle_1_time'],f['red_candle_2_time'],f['red_candle_3_time'],f['rule_version'])).fetchone()
                if natural and natural['setup_id']!=f['setup_id']:raise ValueError('NATURAL_KEY_ID_COLLISION')
                if row is None:
                    insert=dict(f,created_at=now,updated_at=now)
                    keys=list(insert)
                    cur.execute('INSERT INTO reversal_setup ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(insert.values()))
                    counts['inserted']+=1;action='INSERT_SETUP'
                else:
                    if any(row[k]!=f[k] for k in IMMUTABLE):
                        raise ValueError('IMMUTABLE_SETUP_FIELD_CONFLICT:'+f['setup_id'])
                    if row['status'] in ('FOUND','EXPIRED','INVALIDATED'):
                        if s['status']=='WAITING_REVERSAL':
                            # Replay of an earlier prefix must not reverse a final state.
                            counts['duplicates_prevented']+=1;action='SKIP_OLD_PREFIX'
                        elif any(row[k]!=f[k] for k in MUTABLE):
                            raise ValueError('TERMINAL_RECOMPUTE_REQUIRES_NEW_VERSION:'+f['setup_id'])
                        else:counts['duplicates_prevented']+=1;action='SKIP_DUPLICATE'
                    elif row['status']=='WAITING_REVERSAL':
                        if s['status']=='WAITING_REVERSAL':counts['duplicates_prevented']+=1;action='SKIP_DUPLICATE'
                        else:
                            fields={k:f[k] for k in MUTABLE}
                            fields['updated_at']=now
                            cur.execute('UPDATE reversal_setup SET '+','.join(k+'=?' for k in fields)+' WHERE setup_id=?',tuple(fields.values())+(f['setup_id'],))
                            counts['updated']+=1;action='UPDATE_SETUP'
                    else:raise ValueError('UNKNOWN_STORED_STATUS')
                newids.add(f['setup_id'])
                counts['actions'].append(dict(action=action,ticker=f['ticker'],setup_id=f['setup_id'],status=f['status'],
                    processing_time=now,candle_time=f['red_candle_3_time'],context_structure_ids=[f['context_structure_id_1'],f['context_structure_id_2']],
                    rule_version=version,reason_code=f['reason_code']))
        for result in results:
            for ev in result['events']:
                if ev['setup_id'] not in newids:raise ValueError('EVENT_WITHOUT_SETUP')
                data=dict(event_id=ev['event_id'],setup_id=ev['setup_id'],event_type=ev['event_type'],
                    event_time=ev['event_time'],available_at=ev['available_at'],reason_code=ev['reason_code'],
                    event_payload=canonical_json(dict(payload=ev['payload'],context_structure_ids=ev['context_structure_ids'],
                        window_crosses_session=ev['window_crosses_session'])),
                    rule_version=ev['rule_version'],config_hash=chash)
                old=cur.execute('SELECT * FROM reversal_setup_event WHERE event_id=?',(ev['event_id'],)).fetchone()
                if old is None:
                    data['created_at']=now
                    keys=list(data)
                    cur.execute('INSERT INTO reversal_setup_event ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(data.values()))
                    counts['events_inserted']+=1
                    counts['actions'].append(dict(action='INSERT_EVENT',ticker=result['ticker'],setup_id=ev['setup_id'],event_id=ev['event_id'],
                        processing_time=now,candle_time=ev['event_time'],status_transition=ev['event_type'],reason_code=ev['reason_code'],
                        context_structure_ids=ev['context_structure_ids'],rule_version=version))
                elif any(old[k]!=value for k,value in data.items()):
                    raise ValueError('CONFLICTING_EVENT_PAYLOAD:'+ev['event_id'])
                else:counts['events_duplicates']+=1
        conn.commit()
    except Exception:
        conn.rollback();raise
    return counts

def export_long_setups(conn):
    """Pure downstream signals, no order or fill price, ordered deterministically."""
    output=[]
    rows=conn.execute("SELECT * FROM reversal_setup WHERE status='FOUND' ORDER BY available_at,ticker,setup_id").fetchall()
    for row in rows:
        r=dict(row)
        assert r['reversal_candle_time'] and r['body_ratio'] is not None
        assert Decimal(r['body_ratio'])>=Decimal('1') and Decimal(r['body_ratio'])<=Decimal('2')
        output.append(dict(signal_type='LONG_SETUP',ticker=r['ticker'],timeframe=r['timeframe'],
            setup_id=r['setup_id'],signal_time=r['reversal_candle_time'],signal_available_at=r['available_at'],
            context_structure_id_1=r['context_structure_id_1'],context_structure_id_2=r['context_structure_id_2'],
            red_candle_1_time=r['red_candle_1_time'],red_candle_2_time=r['red_candle_2_time'],
            red_candle_3_time=r['red_candle_3_time'],reversal_candle_time=r['reversal_candle_time'],
            body_ratio=r['body_ratio'],rule_version=r['rule_version'],config_hash=r['config_hash'],
            reason_code='REVERSAL_PATTERN_FOUND',context_age_bars=r['context_age_bars'],
            window_crosses_session=bool(r['window_crosses_session']),
            calendar_source_verification=r['calendar_source_verification'],
            # No execution_time, fill_price, stop_loss or take_profit in Layer3.
            ))
    return output

def statistics(conn):
    status={r['status']:r['count'] for r in conn.execute('SELECT status,COUNT(*) count FROM reversal_setup GROUP BY status')}
    return dict(setups=sum(status.values()),events=conn.execute('SELECT COUNT(*) FROM reversal_setup_event').fetchone()[0],
                by_status=status,signals=len(export_long_setups(conn)))
