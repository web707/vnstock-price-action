"""Research-only OAT validation. Production modules and configs are unchanged."""
import copy,json,math
from pathlib import Path
from decimal import Decimal
import pandas as pd
from .phase1 import ts,build_labels
from .phase3 import StructureEngine
from .phase3_rules import RuleProvider
ROOT=Path(__file__).resolve().parents[1]
SCENARIOS=('BASELINE','D05_TICK_PROXY','D05_PCT_0_1','D06_C','D07_C','D04_2_5','D01_OVERLAP_DIAGNOSTIC')
def scenario_config(name):
 if name not in SCENARIOS:raise ValueError('Unknown experiment')
 c=RuleProvider().as_dict();c['rule_version']='sfs-layer2-phase5-research-'+name.lower()+'-v1'
 c['reason_codes']['missing_protected_atr']='PROTECTED_PIVOT_ATR_MISSING'
 c['experiment']=dict(name=name,status='RESEARCH_ONLY_NOT_DEFAULT',tolerance='CURRENT',buffer_atr=0.,consecutive_closes=1,classification_atr=3.,overlap=False,tick_numeric_epsilon_vnd=.01,tick_metadata=json.loads((ROOT/'config/layer2_phase5_tick_metadata.json').read_text()),pit_scope='FIXED_SNAPSHOT_NOT_AS_RECEIVED')
 e=c['experiment'];changes={'D05_TICK_PROXY':('tolerance','ADJUSTED_TICK_PROXY'),'D05_PCT_0_1':('tolerance','PCT_0_1'),'D06_C':('buffer_atr',.5),'D07_C':('consecutive_closes',2),'D04_2_5':('classification_atr',2.5),'D01_OVERLAP_DIAGNOSTIC':('overlap',True)}
 if name in changes:k,v=changes[name];e[k]=v
 return c
class ResearchRules(RuleProvider):
 def __init__(self,c):
  super().__init__(c);e=self.get('experiment')
  if e['tolerance'] not in ('CURRENT','PCT_0_1','ADJUSTED_TICK_PROXY') or e['consecutive_closes'] not in (1,2) or e['buffer_atr'] not in (0,.5):raise ValueError('Unsupported experiment')
 def effective_tick(self,r):
  m=self.get('experiment')['tick_metadata'].get(r['ticker'])
  if m is None:raise ValueError('TICK_METADATA_MISSING')
  factor=math.prod(a['ratio'] for a in m['split_proxy'] if a['date']>str(pd.Timestamp(r['extreme_time']).date()))
  if not math.isfinite(factor) or factor<=0:raise ValueError('Invalid factor')
  if m['exchange']!='HOSE':raise ValueError('Only dataset HOSE stocks supported')
  p=r['extreme_price']*factor*m['unit_scale'];tick=10 if p<10000 else 50 if p<50000 else 100
  return tick/factor/m['unit_scale']
 def tolerance(self,a,b):
  e=self.get('experiment');p=Decimal(str(b['extreme_price']))
  if e['tolerance']=='CURRENT':return max(Decimal(str(self.get('min_tick_tolerance'))),p*Decimal(str(self.get('equal_price_pct'))))
  if e['tolerance']=='PCT_0_1':return p*Decimal('.001')
  return Decimal(str(max(self.effective_tick(a),self.effective_tick(b))))+Decimal(str(e['tick_numeric_epsilon_vnd']))
 def geometry(self,w,d):
  if not d:return False
  for a,b,op in self.get('directions')[d]['relations']:
   if b>=len(w):continue
   x,y=Decimal(str(w[a]['extreme_price'])),Decimal(str(w[b]['extreme_price']));tol=self.tolerance(w[a],w[b])
   if not (y>x+tol if op=='GT' else y<x-tol):return False
  return True
 def level(self,w):
  r=w[self.get('protected_swing_index')];level=r['extreme_price'];buffer=self.get('experiment')['buffer_atr']
  if buffer:
   atr=r['atr_at_extreme']
   if atr is None or not math.isfinite(float(atr)) or atr<=0:return None
   level+=(-1 if self.direction(w)=='UP' else 1)*buffer*atr
  return level
def rules_for(name):return ResearchRules(scenario_config(name))
class ResearchEngine(StructureEngine):
 def __init__(self,s,b,provider):super().__init__(s,b,provider);self.streak={}
 def _on_bar(self,raws,now):
  active={k:r for k,r in self.records.items() if r['status']=='CONFIRMED'};original_order=self.records.copy()
  for k in active:self.records.pop(k)
  n=len(self.calendar)
  try:super()._on_bar(raws,now)
  finally:self.records=original_order
  if len(self.calendar)==n:self.streak.clear();return
  b=self.last_bar
  for sid,r in active.items():
   if b['Datetime']<r['confirmed_at']:continue
   self.streak[sid]=self.streak.get(sid,0)+1 if self.rules.crosses(r['structure_direction'],b['Close'],r['protected_level']) else 0
   if self.streak[sid]>=self.rules.get('experiment')['consecutive_closes']:
    r.update(invalidated_at=now,break_candle_time=b['Datetime'],break_price=b['Close']);self._event(r,'BROKEN','broken',now,b['Datetime'])
 def _progress(self,now):
  n=self.rules.get('min_swings');f=self.rules.get('forming_swings')
  while len(self.accepted)-self.cursor>=f:
   partial=self.accepted[self.cursor:self.cursor+f];d=self.rules.direction(partial)
   if self.current is None:
    if not self.rules.geometry(partial,d):self.note('STRUCTURE_RULE_NOT_MET',now,'INFO',start_swing_id=partial[0]['swing_id']);self.cursor+=1;continue
    self._new(partial,d,now)
   if len(self.accepted)-self.cursor<n:return
   w=self.accepted[self.cursor:self.cursor+n];r=self.records[self.current]
   r.update(end_swing_id=w[-1]['swing_id'],end_time=w[-1]['extreme_time'],swing_ids=[x['swing_id'] for x in w])
   if not self.rules.geometry(w,d):self._event(r,'UNCLEAR','geometry_failure',now,w[-1]['extreme_time']);self.cursor+=1;self.current=None;continue
   amp=abs(w[-1]['extreme_price']-w[0]['extreme_price']);atr=w[0]['atr_at_extreme'];ratio=None if atr is None else amp/atr
   r.update(geometry_qualified=True,geometry_available_at=now,amplitude=amp,atr_reference=atr,amplitude_atr=ratio,amplitude_filter_passed=None if ratio is None else ratio>=self.rules.get('atr_multiplier'))
   if r['protected_level'] is None:self._event(r,'UNCLEAR','missing_protected_atr',now,w[-1]['extreme_time'])
   elif self.last_bar is None:self._event(r,'UNCLEAR','missing_price',now,w[-1]['extreme_time'])
   elif self.rules.crosses(d,self.last_bar['Close'],r['protected_level']):
    r.update(rejected_at=now,rejection_price=self.last_bar['Close'],rejection_candle_time=self.last_bar['Datetime']);self._event(r,'UNCLEAR','pre_broken',now,w[-1]['extreme_time'])
   else:r['confirmed_at']=now;self._event(r,'CONFIRMED','confirmed',now,w[-1]['extreme_time'])
   self.cursor+=1 if self.rules.get('experiment')['overlap'] else n-1;self.current=None

def canonical_rows(frame):
 rows=frame.drop(columns=['created_at','updated_at'],errors='ignore').to_dict('records')
 for r in rows:
  for k,v in r.items():
   if not isinstance(v,(list,dict)) and pd.isna(v):r[k]=None
 return json.dumps(rows,sort_keys=True,default=str)
def batch_oracle(swings,bars,as_of,rules):
 """Independent window/candle scan; clean monotone snapshots only; no lifecycle engine."""
 cfg=rules.phase1_config();cut=ts(as_of,cfg);rows=build_labels(swings,bars,as_of=cut,config=cfg)['sequence'].to_dict('records')
 if len(rows)!=len(swings):raise ValueError('Oracle requires clean unique complete input')
 for r in rows:
  if pd.isna(r['atr_at_extreme']):r['atr_at_extreme']=None
 if any(a['confirmed_at']>b['confirmed_at'] for a,b in zip(rows,rows[1:])):raise ValueError('Oracle requires monotone confirmation')
 candles=[]
 for r in bars.to_dict('records'):
  r['Datetime']=ts(r['Datetime'],cfg);r['closed']=r['Datetime']+pd.Timedelta(minutes=15)
  if r['closed']<=cut:candles.append(r)
 candles.sort(key=lambda x:x['Datetime']);out=[];i=0
 while i+4<=len(rows):
  w=rows[i:i+4];d=rules.direction(w)
  if not rules.geometry(w,d):i+=1;continue
  at=max(x['confirmed_at'] for x in w);level=rules.level(w);available=[b for b in candles if b['closed']<=at];last=available[-1] if available else None
  r=dict(start_swing_id=w[0]['swing_id'],end_swing_id=w[-1]['swing_id'],structure_direction=d,protected_level=level,geometry_available_at=at,confirmed_at=None,invalidated_at=None,status='UNCLEAR')
  if level is not None and last is not None and not rules.crosses(d,last['Close'],level):
   r.update(confirmed_at=at,status='CONFIRMED');streak=0
   for b in candles:
    if b['Datetime']<at:continue
    streak=streak+1 if rules.crosses(d,b['Close'],level) else 0
    if streak>=rules.get('experiment')['consecutive_closes']:r.update(status='BROKEN',invalidated_at=b['closed']);break
  out.append(r);i+=1 if rules.get('experiment')['overlap'] else 3
 return out
