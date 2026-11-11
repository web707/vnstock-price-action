"""Phase 3: point-in-time in-memory reversal-candidate lifecycle, NO SQL/LONG_SETUP.

Update WAITING candidates first at a candle, then CREATE from R3. Context-break
at identical available_at to G takes precedence over G. All time decisions use
available_at, never end_time or final Layer2 state. No implicit backtest orders.
"""
import copy
from datetime import datetime
from decimal import Decimal
from collections import Counter
from .candles import analyze, digest, number

TERMINAL=frozenset({'FOUND','EXPIRED','INVALIDATED'})

def _iso(t,rules):return rules.timestamp(t).isoformat()

def _context_still_valid(provider,setup,at,source_version):
    """Check original two IDs, not the latest favorable pair or ACTIVE fallback."""
    snap=provider.snapshot(at,ticker=setup['ticker'],timeframe=setup['timeframe'],source_version=source_version)
    indexed={x['structure_id']:x for x in snap['major_sequence']}
    missing=[i for i in setup['context_structure_ids'] if i not in indexed]
    if missing:return False,'CONTEXT_STRUCTURE_MISSING_AFTER_CREATION',missing
    for i in setup['context_structure_ids']:
        x=indexed[i]
        if x['status']=='BROKEN' or (x.get('invalidated_at') and provider.upstream.timestamp(x['invalidated_at'])<=provider.upstream.timestamp(at)):
            return False,'CONTEXT_STRUCTURE_BROKEN',[i]
        if x['status']!='CONFIRMED':
            return False,'CONTEXT_STRUCTURE_NO_LONGER_CONFIRMED',[i]
    return True,None,[]

def scan_lifecycle(rows,rules,calendar,provider,*,as_of,ticker,timeframe,source_version):
    """Return deterministic serializable snapshots and in-memory transition events.

    Requires the Phase1/2 candle scanner and Layer2 *event* provider. Historical
    revisions/corrections are a new replay, never silently overwritten here.
    A source bar available out of chronological order cannot be backfilled into
    an earlier candidate: it is diagnosed as LATE_TRIPLET_AVAILABILITY.
    """
    if provider.rules.config_hash!=rules.config_hash:
        raise ValueError('CONTEXT_RULE_HASH_MISMATCH')
    if calendar.binding!=(rules.get('timeframe'),rules.get('timestamp_label'),rules.get('timezone')):
        raise ValueError('CALENDAR_RULE_BINDING_MISMATCH')
    until=rules.timestamp(as_of)
    data=analyze(rows,rules,calendar,as_of=until)
    candles=[x for x in data['candles'] if x['ticker']==ticker and x['timeframe']==timeframe]
    triplets=[x for x in data['triplets'] if x['ticker']==ticker and x['timeframe']==timeframe]
    by_r3={p['red_candle_times'][2]:p for p in triplets}
    # At a T with simultaneous Layer2 changes + completed candle, the context event
    # is projected FIRST so a BROKEN is not turned into a fictitious FOUND.
    timeline=[]
    for when in set(provider._times):
        if when<=until:timeline.append((when,0,-1,None))
    for i,c in enumerate(candles):
        timeline.append((rules.timestamp(c['available_at']),1,i,c))
    timeline.sort(key=lambda row:(row[0],row[1],row[2]))
    candidates={};events=[]; diagnostics=[]
    def transition(s,status,why,when,*,candle=None,ratio=None,details=None):
        if status=='WAITING_REVERSAL':event_type='CREATED'
        elif status=='FOUND':event_type='REVERSAL_FOUND'
        else:event_type=status
        s['status']=status;s['reason_code']=why;s['available_at']=_iso(when,rules)
        if status in TERMINAL:s['resolved_at']=_iso(when,rules)
        if candle is not None and status=='FOUND':
            s['reversal_candle_time']=candle['candle_time']
            s['reversal_candle']=copy.deepcopy({k:candle.get(k) for k in ['candle_time','open','high','low','close','volume','available_at']})
            s['reversal_body']=candle['body'];s['body_ratio']=str(ratio)
            s['found_at']=_iso(when,rules)
        ev=dict(event_id=digest([s['setup_id'],event_type,_iso(when,rules),why]),
            setup_id=s['setup_id'],event_type=event_type,event_time=_iso(when,rules),
            available_at=_iso(when,rules),reason_code=why,rule_version=rules.version,
            context_structure_ids=s['context_structure_ids'],
            window_crosses_session=s['window_crosses_session'],
            payload=details or {})
        events.append(ev)
    for now,kind,_,c in timeline:
        if kind==0:
            for s in candidates.values():
                if s['status']!='WAITING_REVERSAL':continue
                ok,reason,broken=_context_still_valid(provider,s,now,source_version)
                if not ok:transition(s,'INVALIDATED',reason,now,details={'structure_ids':broken})
            continue
        if c is None:continue
        # Step 11.4.a: existing candidates before considering R3 in this bar.
        for s in candidates.values():
            if s['status']!='WAITING_REVERSAL':continue
            current_index=c['calendar_index'];previous=s['last_calendar_index']
            if current_index is not None and current_index<=previous:continue
            if c['candle_time']<=s['red_candle_times'][2]:continue
            if current_index is None or not c['valid']:
                transition(s,'INVALIDATED','INVALID_CANDLE_DATA',now,details={'candle_time':c['candle_time'],'details':c['reason_codes']})
                continue
            if current_index != previous+1:
                transition(s,'INVALIDATED','DATA_GAP_IN_CANDLE_SEQUENCE',now,details={'expected_index':previous+1,'actual_index':current_index})
                continue
            cross=c['session_id'] != s['last_session_id']
            if cross:s['observed_window_crosses_session']=True
            if cross and not rules.get('allow_cross_session_sequences'):
                transition(s,'INVALIDATED','CROSS_SESSION_WINDOW_BLOCKED',now,details={'candle_time':c['candle_time']})
                continue
            ok,reason,broken=_context_still_valid(provider,s,now,source_version)
            if not ok:
                transition(s,'INVALIDATED',reason,now,details={'structure_ids':broken})
                continue
            s['last_calendar_index']=current_index;s['last_session_id']=c['session_id']
            s['bars_checked']+=1
            body3=number(s['body_3'])
            ratio=None
            if c['color']=='GREEN':
                ratio=number(c['body'])/body3
                if number(rules.get('body_ratio_min'))<=ratio<=number(rules.get('body_ratio_max')):
                    transition(s,'FOUND','REVERSAL_CANDLE_FOUND',now,candle=c,ratio=ratio)
                    continue
                reason='REVERSAL_BODY_RATIO_TOO_SMALL' if ratio<number(rules.get('body_ratio_min')) else 'REVERSAL_BODY_RATIO_TOO_LARGE'
            else:reason='NOT_GREEN_CANDLE'
            s['window_checks'].append(dict(candle_time=c['candle_time'],available_at=c['available_at'],reason_code=reason,ratio=str(ratio) if ratio is not None else None))
            if s['bars_checked']==rules.get('max_wait_candles'):
                transition(s,'EXPIRED','REVERSAL_NOT_FOUND_WITHIN_WINDOW',now)
        # Step 11.4.b/c: creation AFTER updating older candidates.
        p=by_r3.get(c['candle_time'])
        if p is None:continue
        at=rules.timestamp(p['available_at'])
        if at>now:
            diagnostics.append(dict(ticker=ticker,red_candle_times=p['red_candle_times'],reason_code='LATE_TRIPLET_AVAILABILITY_NO_BACKDATE'))
            continue
        ctx=provider.evaluate_triplet(p,data['candles'],source_version=source_version)
        if not ctx['context_valid']:continue
        key=(ticker,timeframe,*p['red_candle_times'],rules.version)
        setup_id=digest(key)
        if setup_id in candidates:
            diagnostics.append(dict(ticker=ticker,setup_id=setup_id,reason_code='DUPLICATE_CANDIDATE_PREVENTED'))
            continue
        s=dict(setup_id=setup_id,pattern_id=p['pattern_id'],ticker=ticker,timeframe=timeframe,
            rule_version=rules.version,config_hash=rules.config_hash,calendar_id=calendar.id,calendar_hash=calendar.hash,
            calendar_verified=calendar.verified,source_version=source_version,
            context_structure_ids=ctx['selected_ids'],context_available_at=ctx['context_available_at'],
            context_age_bars=ctx['context_age_bars'],context_age_coverage_complete=ctx['context_age_coverage_complete'],
            red_candle_times=p['red_candle_times'],red_candles=copy.deepcopy(p['candles']),
            body_1=p['candles'][0]['body'],body_3=p['candles'][2]['body'],
            total_wick_1=p['candles'][0]['total_wick'],total_wick_3=p['candles'][2]['total_wick'],
            red_triplet_crosses_session=p['cross_session'],
            window_crosses_session=any(slot['session_id'] != p['candles'][2]['session_id'] for slot in calendar.slots[p['candles'][2]['calendar_index']+1:p['candles'][2]['calendar_index']+1+rules.get('max_wait_candles')]),
            observed_window_crosses_session=False,
            bars_checked=0,last_calendar_index=p['candles'][2]['calendar_index'],
            last_session_id=p['candles'][2]['session_id'],window_checks=[],
            setup_detected_at=_iso(now,rules),available_at=_iso(now,rules),
            resolved_at=None,found_at=None,reversal_candle_time=None,
            reversal_candle=None,reversal_body=None,body_ratio=None,
            status='WAITING_REVERSAL',reason_code='SETUP_CREATED')
        candidates[setup_id]=s
        transition(s,'WAITING_REVERSAL','SETUP_CREATED',now)
    out=[copy.deepcopy(x) for x in candidates.values()]
    metrics=Counter(x['status'] for x in out)
    return dict(ticker=ticker,timeframe=timeframe,rule_version=rules.version,config_hash=rules.config_hash,
        as_of=_iso(until,rules),calendar_id=calendar.id,calendar_hash=calendar.hash,calendar_verified=calendar.verified,
        candidates=out,events=events,diagnostics=diagnostics,
        metrics=dict(total_candles_processed=len(candles),invalid_candles=sum(not c['valid'] for c in candles),
            data_gaps=len(data['gaps']),valid_red_triplets=len(triplets),candidates_created=len(out),
            found=metrics['FOUND'],expired=metrics['EXPIRED'],invalidated=metrics['INVALIDATED'],
            waiting=metrics['WAITING_REVERSAL'],duplicate_candidates_prevented=sum(d['reason_code']=='DUPLICATE_CANDIDATE_PREVENTED' for d in diagnostics),
            found_ratio=(metrics['FOUND']/len(out)) if out else 0.0))
