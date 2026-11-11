"""Versioned, immutable rule provider. Unsupported policies fail explicitly."""
import copy, hashlib, json
from pathlib import Path
from decimal import Decimal
from .phase1 import Config

class RuleProvider:
    def __init__(self, config=None):
        self._c=copy.deepcopy(config if config is not None else json.loads((Path(__file__).resolve().parents[1]/'config/layer2_phase3_baseline.json').read_text()))
        c=self._c
        c.setdefault('break_basis',None);c.setdefault('break_rule_status','UNCONFIGURED')
        for d in c['directions'].values():d.setdefault('break_operator',None)
        if not c['rule_version']:raise ValueError('rule_version required')
        supported={'sequence_policy':'NO_REUSED_LEGS_SHARED_ENDPOINT','forming_rule':'ALL_AVAILABLE_RELATIONS','protected_level_rule':'FIXED_CORRECTION_PIVOT','amplitude_role':'DIAGNOSTIC_ONLY','classification':'UNCLASSIFIED','break_bar_policy':'OPEN_AT_OR_AFTER_CONFIRMATION','price_at_availability':'LATEST_CLOSED_CANDLE','late_swing_policy':'QUARANTINE_AFTER_PUBLISHED_HISTORY','candle_label':'open','timeframe':'15m'}
        for key,value in supported.items():
            if c.get(key)!=value:raise ValueError('Unsupported policy: '+key)
        if c['min_swings']!=4 or c['forming_swings']!=3 or c['protected_swing_index']!=2 or c['bar_minutes']!=15:raise ValueError('Only approved four-swing baseline supported')
        if not c['consume_geometry_even_if_unconfirmed']:raise ValueError('Cannot refill rejected geometry')
        if c['break_basis'] not in (None,'CLOSE'):raise ValueError('Only CLOSE approved')
        if any(v['enabled'] for v in c['phase5_variants'].values()):raise ValueError('Phase 5 variants disabled')
        for k in ('pre_broken_status','geometry_failure_status','missing_price_status'):
            if c[k]!='UNCLEAR':raise ValueError('Unapproved rejection state')
        self.phase1_config()
    @property
    def version(self):return self._c['rule_version']
    @property
    def config_hash(self):return hashlib.sha256(json.dumps(self._c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def get(self,k):return copy.deepcopy(self._c[k])
    def as_dict(self):return copy.deepcopy(self._c)
    def phase1_config(self):
        return Config(**{k:self._c[k] for k in ('rule_version','timezone','min_tick_tolerance','equal_price_pct','pivot_right','candle_label')})
    def direction(self,w):
        for name,d in self._c['directions'].items():
            if [r['swing_type'] for r in w]==d['pattern'][:len(w)]:return name
    def geometry(self,w,direction):
        if not direction:return False
        for a,b,op in self._c['directions'][direction]['relations']:
            if b>=len(w):continue
            x,y=Decimal(str(w[a]['extreme_price'])),Decimal(str(w[b]['extreme_price']))
            tol=max(Decimal(str(self._c['min_tick_tolerance'])),abs(y)*Decimal(str(self._c['equal_price_pct'])))
            if not (y>x+tol if op=='GT' else y<x-tol):return False
        return True
    def level(self,w):return w[self._c['protected_swing_index']]['extreme_price']
    def break_configured(self,d):
        return self._c['break_basis']=='CLOSE' and self._c['break_rule_status']=='APPROVED' and self._c['directions'][d]['break_operator'] in ('LT','GT')
    def crosses(self,d,price,level):
        return price<level if self._c['directions'][d]['break_operator']=='LT' else price>level
    def reason(self,k):return self._c['reason_codes'][k]
    def permits(self,old,new):return new in self._c['transitions'].get(old or 'NONE',[])
