"""Point-in-time four-swing structure replay. No Major or Long-context logic."""
import copy, hashlib, json, math
import pandas as pd
from .phase1 import build_labels, ts
from .phase3_rules import RuleProvider

STRUCTURE_COLUMNS='structure_id ticker timeframe structure_sequence_no previous_major_structure_id start_swing_id end_swing_id start_time end_time structure_direction classification status amplitude amplitude_atr atr_reference atr_multiplier protected_level break_basis break_level confirmed_at available_at invalidated_at break_candle_time break_price reason_code rule_version source_version created_at updated_at protected_swing_id break_operator event_time formation_available_at geometry_available_at amplitude_filter_passed config_hash swing_ids geometry_qualified rejected_at rejection_candle_time rejection_price'.split()
EVENT_COLUMNS='event_id structure_id old_status new_status event_type event_time available_at reason_code source_version rule_version payload_json event_sequence config_hash'.split()
TIME_COLUMNS='start_time end_time confirmed_at available_at invalidated_at break_candle_time event_time formation_available_at geometry_available_at rejected_at rejection_candle_time'.split()

def stable_id(values):return hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()[:32]
def semantic(r):return {k:v for k,v in r.items() if k not in ('created_at','updated_at')}
def decode_snapshot(s):
    r=json.loads(s)['after']
    for k in TIME_COLUMNS:
        if r.get(k) is not None:r[k]=pd.Timestamp(r[k])
    return r

class StructureEngine:
    """Immutable input snapshots; advance a replay cursor, or query historical events."""
    def __init__(self,swings,ohlcv,provider=None):
        self.rules=provider or RuleProvider();self.cfg=self.rules.phase1_config()
        self.raw=swings.copy(deep=True);self.bars=ohlcv.copy(deep=True)
        self.records={};self.events=[];self.audit=[];self.accepted=[];self.eligible=[];self.calendar=[]
        self.cursor=0;self.current=None;self.last_bar=None;self.watermark=None;self.next=0
        schedule={}
        for i,r in enumerate(self.raw.to_dict('records')):
            try:t=ts(r['confirmed_at'],self.cfg)
            except (ValueError,TypeError,KeyError):self.note('INVALID_TIMESTAMP',None,row=i);continue
            schedule.setdefault(t,{'bars':[],'swings':[]})['swings'].append(i)
        for r in self.bars.to_dict('records'):
            try:t=ts(r['Datetime'],self.cfg)+pd.Timedelta(minutes=self.rules.get('bar_minutes'))
            except (ValueError,TypeError,KeyError):self.note('INVALID_TIMESTAMP',None,table='OHLCV');continue
            schedule.setdefault(t,{'bars':[],'swings':[]})['bars'].append(r)
        self.timeline=sorted(schedule.items())
    def note(self,reason,at,severity='QUARANTINE',**details):
        self.audit.append(dict(reason_code=reason,available_at=at,severity=severity,payload_json=json.dumps(details,default=str)))
    def _event(self,r,new,key,now,event_time):
        old=r['status']
        if not self.rules.permits(old,new):raise ValueError('Forbidden state transition')
        r.update(status=new,available_at=now,event_time=event_time,reason_code=self.rules.reason(key),updated_at=pd.Timestamp.now(tz='UTC').isoformat())
        seq=1+sum(e['structure_id']==r['structure_id'] for e in self.events)
        e=dict(structure_id=r['structure_id'],old_status=old,new_status=new,event_type=new,event_time=event_time,available_at=now,reason_code=r['reason_code'],source_version=r['source_version'],rule_version=self.rules.version,config_hash=self.rules.config_hash,event_sequence=seq,payload_json=json.dumps({'after':semantic(r)},sort_keys=True,default=str,allow_nan=False))
        e['event_id']=stable_id(e);self.events.append(copy.deepcopy(e))
    def _on_bar(self,raws,now):
        valid=[]
        for raw in raws:
            try:
                r=copy.deepcopy(raw);r['Datetime']=ts(r['Datetime'],self.cfg)
                o,h,l,c,v=[float(r[k]) for k in ('Open','High','Low','Close','Volume')]
                if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError()
                r.update(Open=o,High=h,Low=l,Close=c,Volume=v);valid.append(r)
            except (ValueError,TypeError,KeyError):self.note('INVALID_PRICE',now,table='OHLCV')
        if not valid:return
        signatures={tuple(r[k] for k in ('Datetime','Open','High','Low','Close','Volume')) for r in valid}
        if len(signatures)>1:self.note('CONFLICTING_CANDLE',now);return
        if len(valid)>1:self.note('DUPLICATE_CANDLE',now,'INFO')
        b=valid[0];self.last_bar=b;self.calendar.append(b)
        for r in self.records.values():
            if r['status']!='CONFIRMED' or b['Datetime']<r['confirmed_at']:continue
            if self.rules.crosses(r['structure_direction'],b['Close'],r['protected_level']):
                r.update(invalidated_at=now,break_candle_time=b['Datetime'],break_price=b['Close'])
                self._event(r,'BROKEN','broken',now,b['Datetime'])
    def _on_swings(self,indices,now):
        self.eligible.extend(indices)
        bars=pd.DataFrame(self.calendar,columns=self.bars.columns)
        res=build_labels(self.raw.iloc[self.eligible],bars,as_of=now,config=self.cfg)
        for a in res['audit'].to_dict('records'):self.note(a['reason_code'],now,a['severity'],input_audit=a)
        new=res['sequence'].to_dict('records')
        for row in new:
            if pd.isna(row['atr_at_extreme']):row['atr_at_extreme']=None
        if not new:return
        keys=('swing_id','swing_type','extreme_price','extreme_time','confirmed_at','source_version','atr_at_extreme')
        sig=lambda rows:[tuple(r[k] for k in keys) for r in rows]
        if sig(new[:len(self.accepted)])!=sig(self.accepted):
            if self.records:self.note('DATA_ORDER_AMBIGUOUS',now,action='retain published history; reject late/corrected sequence');return
            self.cursor=0
        self.accepted=new;self._progress(now)
    def _new(self,w,d,now):
        sid=stable_id([w[0]['ticker'],w[0]['timeframe'],w[0]['source_version'],self.rules.version,[x['swing_id'] for x in w]])
        r=dict.fromkeys(STRUCTURE_COLUMNS)
        r.update(structure_id=sid,ticker=w[0]['ticker'],timeframe=w[0]['timeframe'],start_swing_id=w[0]['swing_id'],end_swing_id=w[-1]['swing_id'],start_time=w[0]['extreme_time'],end_time=w[-1]['extreme_time'],structure_direction=d,classification=self.rules.get('classification'),atr_multiplier=self.rules.get('atr_multiplier'),protected_level=self.rules.level(w),break_level=self.rules.level(w),protected_swing_id=w[self.rules.get('protected_swing_index')]['swing_id'],break_basis=self.rules.get('break_basis'),break_operator=self.rules.get('directions')[d]['break_operator'],rule_version=self.rules.version,source_version=w[0]['source_version'],config_hash=self.rules.config_hash,swing_ids=[x['swing_id'] for x in w],geometry_qualified=False,formation_available_at=now,created_at=pd.Timestamp.now(tz='UTC').isoformat())
        self.records[sid]=r;self.current=sid;self._event(r,'FORMING','forming',now,w[-1]['extreme_time'])
    def _progress(self,now):
        n=self.rules.get('min_swings');f=self.rules.get('forming_swings')
        while len(self.accepted)-self.cursor>=f:
            partial=self.accepted[self.cursor:self.cursor+f];d=self.rules.direction(partial)
            if self.current is None:
                if not self.rules.geometry(partial,d):
                    self.note('STRUCTURE_RULE_NOT_MET',now,'INFO',start_swing_id=partial[0]['swing_id']);self.cursor+=1;continue
                self._new(partial,d,now)
            if len(self.accepted)-self.cursor<n:return
            w=self.accepted[self.cursor:self.cursor+n];r=self.records[self.current]
            r.update(end_swing_id=w[-1]['swing_id'],end_time=w[-1]['extreme_time'],swing_ids=[x['swing_id'] for x in w])
            if not self.rules.geometry(w,d):
                self._event(r,self.rules.get('geometry_failure_status'),'geometry_failure',now,w[-1]['extreme_time']);self.cursor+=1;self.current=None;continue
            amp=abs(w[-1]['extreme_price']-w[0]['extreme_price']);atr=w[0]['atr_at_extreme'];ratio=None if atr is None else amp/atr
            r.update(geometry_qualified=True,geometry_available_at=now,amplitude=amp,atr_reference=atr,amplitude_atr=ratio,amplitude_filter_passed=None if ratio is None else ratio>=self.rules.get('atr_multiplier'))
            if not self.rules.break_configured(d):self._event(r,'UNCLEAR','break_not_configured',now,w[-1]['extreme_time'])
            elif self.last_bar is None:self._event(r,self.rules.get('missing_price_status'),'missing_price',now,w[-1]['extreme_time'])
            elif self.rules.crosses(d,self.last_bar['Close'],r['protected_level']):
                r.update(rejected_at=now,rejection_price=self.last_bar['Close'],rejection_candle_time=self.last_bar['Datetime'])
                self._event(r,self.rules.get('pre_broken_status'),'pre_broken',now,w[-1]['extreme_time'])
            else:
                r['confirmed_at']=now;self._event(r,'CONFIRMED','confirmed',now,w[-1]['extreme_time'])
            self.cursor+=n-1;self.current=None
    def advance(self,as_of):
        t=ts(as_of,self.cfg)
        if self.watermark is not None and t<self.watermark:raise ValueError('Replay cursor cannot rewind; use snapshot')
        while self.next<len(self.timeline) and self.timeline[self.next][0]<=t:
            now,group=self.timeline[self.next]
            if group['bars']:self._on_bar(group['bars'],now)
            if group['swings']:self._on_swings(group['swings'],now)
            self.next+=1
        self.watermark=t;return self.snapshot(t)
    def snapshot(self,as_of):
        t=ts(as_of,self.cfg)
        if self.watermark is None or t>self.watermark:raise ValueError('Advance before querying future')
        events=[copy.deepcopy(e) for e in self.events if e['available_at']<=t];rows={}
        for e in events:rows[e['structure_id']]=decode_snapshot(e['payload_json'])
        for r in rows.values():
            original=self.records[r['structure_id']];r['created_at']=original['created_at'];r['updated_at']=str(r['available_at'])
        records=list(rows.values());audit=[copy.deepcopy(a) for a in self.audit if a['available_at'] is None or a['available_at']<=t]
        counts={s:sum(r['status']==s for r in records) for s in ('FORMING','CONFIRMED','BROKEN','UNCLEAR')}
        log=dict(rule_version=self.rules.version,config_hash=self.rules.config_hash,as_of=str(t),structures=len(records),events=len(events),geometry_qualified=sum(r['geometry_qualified'] for r in records),ever_confirmed=sum(r['confirmed_at'] is not None for r in records),rejected_at_birth=sum(r['rejected_at'] is not None for r in records),**counts)
        return dict(market_structure=pd.DataFrame(records,columns=STRUCTURE_COLUMNS),market_structure_event=pd.DataFrame(events,columns=EVENT_COLUMNS),audit=pd.DataFrame(audit,columns=['reason_code','available_at','severity','payload_json']),batch_log=log,rule_config=self.rules.as_dict())

def build_structures(swings,ohlcv,*,as_of,provider=None):return StructureEngine(swings,ohlcv,provider).advance(as_of)
