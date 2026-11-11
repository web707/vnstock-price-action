"""Versioned classification and point-in-time Major/context queries over Phase 3 events."""
import copy, hashlib, json, math
from pathlib import Path
from decimal import Decimal
import pandas as pd

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=lambda x:x.isoformat() if isinstance(x,pd.Timestamp) else str(x))
def digest(obj):return hashlib.sha256(canonical(obj).encode()).hexdigest()

class ContextRules:
    def __init__(self,config=None):
        self._c=copy.deepcopy(config if config is not None else json.loads((Path(__file__).resolve().parents[1]/'config/layer2_phase4_baseline.json').read_text()))
        c=self._c
        if not c['rule_version'] or not c['upstream_rule_version'] or not c['upstream_config_hash']:raise ValueError('Version binding required')
        if isinstance(c['amplitude_threshold_atr'],bool) or not math.isfinite(float(c['amplitude_threshold_atr'])) or c['amplitude_threshold_atr']<=0:raise ValueError('Invalid amplitude threshold')
        supported={'classification_operator':'GE','classification_scope':'EVER_CONFIRMED','missing_atr_classification':'UNCLASSIFIED','sequence_order':['confirmed_at','end_time','start_time','structure_id'],'directions':['UP','DOWN'],'query_modes':['EVER_CONFIRMED','ACTIVE'],'default_query_mode':None,'active_status':'CONFIRMED','long_enabled':False,'is_long_candidate':None,'long_reason':'LONG_CONTEXT_NOT_EVALUATED','pair_size':2}
        for k,v in supported.items():
            if c[k]!=v:raise ValueError('Unsupported/unapproved policy: '+k)
    @property
    def version(self):return self._c['rule_version']
    @property
    def config_hash(self):return digest(self._c)
    def get(self,key):return copy.deepcopy(self._c[key])
    def as_dict(self):return copy.deepcopy(self._c)
    def timestamp(self,value):
        if value is None or isinstance(value,(bool,int,float)) or pd.isna(value):raise ValueError('Invalid timestamp')
        t=pd.Timestamp(value)
        return t.tz_localize(self.get('timezone')) if t.tzinfo is None else t.tz_convert(self.get('timezone'))
    def classify(self,row):
        if row.get('confirmed_at') is None:return 'UNCLASSIFIED','STRUCTURE_NOT_CONFIRMED'
        atr=row.get('atr_reference');ratio=row.get('amplitude_atr')
        if atr is None or ratio is None or not math.isfinite(float(atr)) or not math.isfinite(float(ratio)) or float(atr)<=0 or float(ratio)<0:
            return self.get('missing_atr_classification'),'ATR_MISSING_OR_INVALID'
        if Decimal(str(ratio))>=Decimal(str(self.get('amplitude_threshold_atr'))):return 'MAJOR','AMPLITUDE_ATR_AT_OR_ABOVE_THRESHOLD'
        return 'INTERNAL','AMPLITUDE_ATR_BELOW_THRESHOLD'

class MajorContext:
    """Immutable event snapshot; queries always require a mode and one source stream."""
    def __init__(self,events,rules=None):
        self.rules=rules or ContextRules()
        raw=events.to_dict('records') if isinstance(events,pd.DataFrame) else list(events)
        self._events=copy.deepcopy(raw)
        for e in self._events:
            for key,value in list(e.items()):
                if value is None or (not isinstance(value,(list,dict)) and pd.isna(value)):e[key]=None
            e['available_at']=self.rules.timestamp(e['available_at'])
    def _project(self,at):
        known=[e for e in self._events if e['available_at']<=at]
        known.sort(key=lambda e:(e['available_at'],str(e['structure_id']),int(e['event_sequence'])))
        states={};seen={};lastseq={}
        for e in known:
            sid=e['structure_id'];seq=int(e['event_sequence']);key=(sid,seq)
            if e['rule_version']!=self.rules.get('upstream_rule_version') or e['config_hash']!=self.rules.get('upstream_config_hash'):raise ValueError('UPSTREAM_VERSION_MISMATCH')
            signature=canonical(e)
            if key in seen:
                if signature!=seen[key]:raise ValueError('CONFLICTING_EVENT')
                continue
            seen[key]=signature
            r=copy.deepcopy(json.loads(e['payload_json'])['after'])
            for k in ('confirmed_at','invalidated_at','available_at','start_time','end_time'):
                if r.get(k) is not None:r[k]=self.rules.timestamp(r[k])
            for k in ('structure_id','rule_version','source_version','config_hash'):
                if r[k]!=e[k]:raise ValueError('EVENT_PAYLOAD_MISMATCH')
            if r['available_at']!=e['available_at'] or r['status']!=e['new_status']:raise ValueError('EVENT_PAYLOAD_MISMATCH')
            old=states.get(sid);oldstatus=old['status'] if old else None
            eold=e.get('old_status');eold=None if eold is None or pd.isna(eold) else eold
            if seq!=lastseq.get(sid,0)+1 or eold!=oldstatus:raise ValueError('INCOMPLETE_EVENT_HISTORY')
            if r['status'] not in self.rules.get('upstream_transitions').get(oldstatus or 'NONE',[]):raise ValueError('INVALID_TRANSITION')
            if old:
                for k in ('ticker','timeframe','source_version','structure_direction','start_swing_id','start_time'):
                    if r[k]!=old[k]:raise ValueError('STRUCTURE_IDENTITY_CHANGED')
                if old.get('confirmed_at') is not None:
                    for k in ('confirmed_at','amplitude_atr','atr_reference','end_time','end_swing_id'):
                        if r.get(k)!=old.get(k):raise ValueError('CONFIRMED_GEOMETRY_CHANGED')
            confirmed=r.get('confirmed_at');broken=r.get('invalidated_at')
            if r['status'] in ('CONFIRMED','BROKEN'):
                if confirmed is None or confirmed>at or confirmed>e['available_at']:raise ValueError('INVALID_CONFIRMATION_TIME')
                if r['status']=='CONFIRMED' and broken is not None:raise ValueError('INVALID_BREAK_TIME')
                if r['status']=='BROKEN' and (broken is None or broken<confirmed or broken!=e['available_at']):raise ValueError('INVALID_BREAK_TIME')
            elif confirmed is not None:raise ValueError('INVALID_CONFIRMATION_STATE')
            states[sid]=r;lastseq[sid]=seq
        return list(states.values())
    def snapshot(self,as_of,*,ticker,timeframe,source_version):
        if not all(isinstance(v,str) and v for v in (ticker,timeframe,source_version)):raise ValueError('Explicit stream required')
        at=self.rules.timestamp(as_of);ticker=ticker.upper()
        rows=[r for r in self._project(at) if (r['ticker'],r['timeframe'],r['source_version'])==(ticker,timeframe,source_version)]
        for r in rows:
            label,reason=self.rules.classify(r)
            if r['structure_direction'] not in self.rules.get('directions'):raise ValueError('Invalid structure direction')
            r.update(upstream_rule_version=r['rule_version'],upstream_config_hash=r['config_hash'],rule_version=self.rules.version,config_hash=self.rules.config_hash,classification=label,classification_reason_code=reason,classification_available_at=r.get('confirmed_at'),classification_threshold_atr=self.rules.get('amplitude_threshold_atr'),structure_sequence_no=None,previous_major_structure_id=None)
        major=[r for r in rows if r['classification']=='MAJOR']
        major.sort(key=lambda r:tuple(r[k] for k in self.rules.get('sequence_order')))
        previous=None
        for n,r in enumerate(major,1):r.update(structure_sequence_no=n,previous_major_structure_id=previous);previous=r['structure_id']
        rows.sort(key=lambda r:(r['start_time'],r['structure_id']))
        metadata=dict(ticker=ticker,timeframe=timeframe,source_version=source_version,as_of_time=at,rule_version=self.rules.version,upstream_rule_version=self.rules.get('upstream_rule_version'))
        snapshot_id=digest(metadata)
        return dict(snapshot_id=snapshot_id,**metadata,config_hash=self.rules.config_hash,rule_config=self.rules.as_dict(),classified_structures=copy.deepcopy(rows),major_sequence=copy.deepcopy(major))
    def last_two(self,as_of,*,ticker,timeframe,source_version,mode):
        if mode not in self.rules.get('query_modes'):raise ValueError('QUERY_MODE_REQUIRED_OR_INVALID')
        return self.context_from_snapshot(self.snapshot(as_of,ticker=ticker,timeframe=timeframe,source_version=source_version),mode=mode)
    def context_from_snapshot(self,snapshot,*,mode):
        if mode not in self.rules.get('query_modes'):raise ValueError('QUERY_MODE_REQUIRED_OR_INVALID')
        if snapshot['rule_version']!=self.rules.version or snapshot['config_hash']!=self.rules.config_hash:raise ValueError('SNAPSHOT_RULE_MISMATCH')
        eligible=snapshot['major_sequence']
        if mode=='ACTIVE':eligible=[r for r in eligible if r['status']==self.rules.get('active_status')]
        pair=copy.deepcopy(eligible[-self.rules.get('pair_size'):]);enough=len(pair)==self.rules.get('pair_size')
        result={k:copy.deepcopy(snapshot[k]) for k in ('snapshot_id','ticker','timeframe','source_version','as_of_time','rule_version','upstream_rule_version','config_hash')}
        result.update(query_mode=mode,eligible_count=len(eligible),selected_count=len(pair),older_structure_id=pair[0]['structure_id'] if enough else None,latest_structure_id=pair[-1]['structure_id'] if pair else None,context_status='OK' if enough else 'INSUFFICIENT_STRUCTURE',selection_reason_code='TWO_STRUCTURES_AVAILABLE' if enough else 'INSUFFICIENT_STRUCTURE',is_long_candidate=self.rules.get('is_long_candidate'),reason_code=self.rules.get('long_reason'),structures=pair)
        result['context_id']=digest([snapshot['snapshot_id'],mode])
        return result
