"""Phase 2: event-only Layer 2 adapter. No candidate creation or reversal lifecycle."""
import copy,json
from bisect import bisect_right
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase4 import MajorContext,ContextRules,canonical
from .candles import Rules,digest

def phase2_rules():
    return Rules(json.loads((Path(__file__).parent/'config/L3_REVERSAL_V1_PHASE2.json').read_text()))

class ContextProvider:
    def __init__(self,events,rules=None,upstream_rules=None):
        self.rules=rules or phase2_rules();self.upstream=upstream_rules or ContextRules()
        if self.rules.get('context_query_mode')!='EVER_CONFIRMED' or self.rules.get('long_context_owner')!='LAYER3':
            raise ValueError('UNAPPROVED_CONTEXT_POLICY')
        if self.rules.get('max_context_age_bars') is not None:raise ValueError('CONTEXT_AGE_FILTER_NOT_ALLOWED')
        rows=events.to_dict('records') if hasattr(events,'to_dict') else list(events)
        self._events=copy.deepcopy(rows)
        for e in self._events:e['available_at']=self.upstream.timestamp(e['available_at'])
        self._events.sort(key=lambda e:(e['available_at'],str(e.get('structure_id')),int(e.get('event_sequence',0))))
        self._times=[e['available_at'] for e in self._events];self._cache={}
    def snapshot(self,at,*,ticker,timeframe,source_version):
        t=self.upstream.timestamp(at);n=bisect_right(self._times,t);key=(n,ticker,timeframe,source_version)
        if key not in self._cache:
            # Strictly cut history BEFORE parsing payload/projecting state. No final-row API.
            history=self._events[:n]
            snap=MajorContext(history,self.upstream).snapshot(t,ticker=ticker,timeframe=timeframe,source_version=source_version)
            self._cache[key]=snap
        snap=copy.deepcopy(self._cache[key]);snap['as_of_time']=t
        snap['snapshot_id']=digest([ticker,timeframe,source_version,t,self.upstream.version,self.upstream.config_hash])
        return snap
    def evaluate(self,at,*,ticker,timeframe,source_version):
        t=self.upstream.timestamp(at);snap=self.snapshot(t,ticker=ticker,timeframe=timeframe,source_version=source_version)
        pair=snap['major_sequence'][-self.upstream.get('pair_size'):]
        reasons=[]
        if len(pair)<self.upstream.get('pair_size'):reasons.append('CONTEXT_NOT_ENOUGH_MAJOR_STRUCTURES')
        else:
            if any(r['available_at']>t for r in pair):reasons.append('CONTEXT_STRUCTURE_NOT_AVAILABLE_YET')
            if any(r['status']=='BROKEN' or (r.get('invalidated_at') is not None and r['invalidated_at']<=t) for r in pair):reasons.append('CONTEXT_STRUCTURE_BROKEN')
            if any(r['structure_direction']!='DOWN' or r['status']!='CONFIRMED' for r in pair):
                # BROKEN already has a specific reason; direction failure remains separately visible.
                if any(r['structure_direction']!='DOWN' for r in pair) or not reasons:reasons.append('CONTEXT_NOT_TWO_ADJACENT_DOWNS')
        if not reasons:reasons=['CONTEXT_TWO_ADJACENT_MAJOR_DOWNS_CONFIRMED']
        valid=reasons==['CONTEXT_TWO_ADJACENT_MAJOR_DOWNS_CONFIRMED']
        result=dict(ticker=ticker,timeframe=timeframe,source_version=source_version,as_of_time=t,
            rule_version=self.rules.version,config_hash=self.rules.config_hash,upstream_rule_version=self.upstream.version,
            upstream_config_hash=self.upstream.config_hash,query_mode=self.rules.get('context_query_mode'),
            major_count=len(snap['major_sequence']),selected_ids=[r['structure_id'] for r in pair],
            structures=pair,context_valid=valid,reason_code=reasons[0],reason_codes=reasons,
            context_available_at=max((r['available_at'] for r in pair),default=None))
        return json.loads(canonical(result))
    def evaluate_triplet(self,triplet,known_candles,*,source_version):
        # Only Phase-1 patterns already known at their own availability may be supplied.
        at=self.rules.timestamp(triplet['available_at'])
        if any(self.rules.timestamp(c['available_at'])>at for c in triplet['candles']):raise ValueError('TRIPLET_NOT_AVAILABLE')
        result=self.evaluate(at,ticker=triplet['ticker'],timeframe=triplet['timeframe'],source_version=source_version)
        result.update(pattern_id=triplet['pattern_id'],red_candle_times=triplet['red_candle_times'],context_age_bars=None,context_age_coverage_complete=False)
        if len(result['structures'])==2:
            end=self.rules.timestamp(result['structures'][1]['end_time']);r3=self.rules.timestamp(triplet['red_candle_times'][-1])
            visible=[c for c in known_candles if c['valid'] and c['ticker']==triplet['ticker'] and c['timeframe']==triplet['timeframe'] and self.rules.timestamp(c['available_at'])<=at]
            result['context_age_bars']=sum(end<self.rules.timestamp(c['candle_time'])<=r3 for c in visible)
            # Count observed valid bars only, no fabricated missing slots; not a filter.
            result['context_age_basis']='OBSERVED_VALID_BARS_OPEN_AFTER_CONTEXT_END_THROUGH_R3'
        return result
