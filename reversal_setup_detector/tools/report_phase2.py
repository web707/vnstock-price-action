import sys,json,csv
from collections import Counter
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from reversal_setup_detector.context import ContextProvider,phase2_rules
from reversal_setup_detector import Calendar,analyze
from reversal_setup_detector.tools.report_phase1 import load_rows,write_csv
from structure_builder_sfs.phase4 import MajorContext
OUT=ROOT/'reports/layer3_phase2';SOURCE='qta-layer1-1.1.0'

def events(t):return pd.read_csv(ROOT/f'reports/layer2_phase3/{t}/market_structure_event.csv')
def boundaries(candles):
    lunch=night=False
    for a,b in zip(candles,candles[1:]):
        if a['candle_time'][:10]!=b['candle_time'][:10]:night=True
        elif a['session_id']!=b['session_id']:lunch=True
    return lunch,night

def main():
    OUT.mkdir(parents=True,exist_ok=True);r=phase2_rules();cal=Calendar.template(r,'2026-08-07 00:00+07:00','2026-10-29 00:00+07:00')
    funnel=[];gap_summary=[];blocked_details=[];timing=[];reason_rows=[];active_summary=[];examples=[]
    for ticker in ['HPG','FPT','VNM','VCB','SSI']:
        rows=load_rows(ticker);data=analyze(rows,r,cal,as_of=cal.end);provider=ContextProvider(events(ticker));stream=dict(ticker=ticker,timeframe='15m',source_version=SOURCE)
        candle_contexts=[];triplet_contexts=[];diff=middle=0;seen_examples=set()
        for c in data['candles']:
            if not c['valid']:continue
            ctx=provider.evaluate(c['available_at'],**stream);candle_contexts.append(ctx)
            snap=provider.snapshot(c['available_at'],**stream)
            active=MajorContext([],provider.upstream).context_from_snapshot(snap,mode='ACTIVE')
            aid=[x['structure_id'] for x in active['structures']]
            if aid!=ctx['selected_ids']:diff+=1
            between=[]
            if len(active['structures'])==2:
                a,b=[x['structure_sequence_no'] for x in active['structures']]
                between=[x for x in snap['major_sequence'] if a<x['structure_sequence_no']<b and x['status']=='BROKEN']
            if between:middle+=1
            signature=tuple(aid+ctx['selected_ids'])
            if between and signature not in seen_examples:
                seen_examples.add(signature)
                examples.append(dict(ticker=ticker,at=c['available_at'],ever_confirmed=ctx['structures'],active=active['structures'],skipped_broken_between=between,layer3_valid=ctx['context_valid'],layer3_reason=ctx['reason_code']))
        for p in data['triplets']:triplet_contexts.append(provider.evaluate_triplet(p,data['candles'],source_version=SOURCE))
        count=Counter(x['reason_code'] for x in candle_contexts);tc=Counter(x['reason_code'] for x in triplet_contexts)
        for stage,rs in [('ALL_CANDLE_TIMES',count),('VALID_RED_TRIPLETS',tc)]:
            for reason,n in sorted(rs.items()):reason_rows.append(dict(ticker=ticker,stage=stage,reason_code=reason,count=n))
        funnel.append(dict(ticker=ticker,candle_times=len(candle_contexts),context_valid_times=sum(x['context_valid'] for x in candle_contexts),red_triplets=len(triplet_contexts),triplets_with_context=sum(x['context_valid'] for x in triplet_contexts),triplets_context_rejected=sum(not x['context_valid'] for x in triplet_contexts)))
        active_summary.append(dict(ticker=ticker,compared_times=len(candle_contexts),active_differs_from_ever=diff,active_skips_broken_between=middle))
        # Phase 1 addendum: adjacent OBSERVED rows passing morphology, test the gap gate last.
        blocked=[];potential=0
        candles=data['candles']
        for i in range(2,len(candles)):
            tri=candles[i-2:i+1]
            if not all(c['valid'] and c['color']=='RED' for c in tri) or not tri[0]['strong'] or not tri[-1]['strong']:continue
            potential+=1;idx=[c['calendar_index'] for c in tri]
            if idx!=list(range(idx[0],idx[0]+3)):
                lunch,night=boundaries(tri)
                item=dict(ticker=ticker,red_candle_times=[c['candle_time'] for c in tri],reason_code='UNVERIFIED_CALENDAR_GAP',cross_lunch=lunch,cross_overnight=night,
                    missing_times=[cal.times[j].isoformat() for j in range(idx[0],idx[-1]+1) if j not in idx])
                blocked.append(item);blocked_details.append(item)
        lunch=night=0
        for p in data['triplets']:
            a,b=boundaries(p['candles']);lunch+=a;night+=b
        # Diagnostics only for five slots after R3, no search for G/lifecycle.
        wl=wn=complete=cl=cn=0;by_idx={c['calendar_index']:c for c in candles if c['valid']}
        for p in data['triplets']:
            n=p['candles'][-1]['calendar_index'];indices=list(range(n+1,n+1+r.get('max_wait_candles')))
            seq=[p['candles'][-1]]+[dict(candle_time=cal.slots[j]['open_at'].isoformat(),session_id=cal.slots[j]['session_id']) for j in indices if j<len(cal.slots)]
            a,b=boundaries(seq);wl+=a;wn+=b;ok=all(j in by_idx for j in indices);complete+=ok;cl+=a and ok;cn+=b and ok
        gap_summary.append(dict(ticker=ticker,morphology_before_gap=potential,blocked_suspected_gap=len(blocked),valid_triplets=len(data['triplets']),valid_cross_lunch=lunch,valid_cross_overnight=night,blocked_cross_lunch=sum(x['cross_lunch'] for x in blocked),blocked_cross_overnight=sum(x['cross_overnight'] for x in blocked),five_slot_cross_lunch=wl,five_slot_cross_overnight=wn,complete_five_slot_windows=complete,complete_window_cross_lunch=cl,complete_window_cross_overnight=cn))
        assert potential==len(blocked)+len(data['triplets'])
        for reason,n in [('INSUFFICIENT_CANDLE_HISTORY',min(2,len(candles))),('THREE_RED_CANDLE_PATTERN_NOT_FOUND',max(0,len(candles)-2)-potential),('UNVERIFIED_CALENDAR_GAP',len(blocked)),('THREE_RED_CANDLE_PATTERN_FOUND',len(data['triplets']))]:
            reason_rows.append(dict(ticker=ticker,stage='CANDLE_PATTERN_GATE',reason_code=reason,count=n))
        swings=pd.read_csv(ROOT/f'reports/layer1_schema/{ticker}.csv');bars=pd.read_csv(ROOT/f'reports/layer1/{ticker}_clean.csv')
        for s in swings.to_dict('records'):
            eb=bars.iloc[int(s['index'])];cb=bars.iloc[int(s['confirmed_at_index'])]
            timing.append(dict(ticker=ticker,swing_id=s['swing_id'],extreme_time=str(r.timestamp(s['extreme_time'])),extreme_candle_open=str(r.timestamp(eb.Datetime)),confirmation_candle_open=str(r.timestamp(cb.Datetime)),confirmed_at=str(r.timestamp(s['confirmed_at'])),confirmation_candle_available=str(r.timestamp(cb.available_time)),extreme_matches_open=r.timestamp(s['extreme_time'])==r.timestamp(eb.Datetime),confirmation_matches_close=r.timestamp(s['confirmed_at'])==r.timestamp(cb.Datetime)+r.duration,confirmation_matches_available=r.timestamp(s['confirmed_at'])==r.timestamp(cb.available_time)))
        for name,values in [('candle_contexts',candle_contexts),('triplet_contexts',triplet_contexts)]:
            (OUT/f'{ticker}_{name}.json').write_text(json.dumps(values,ensure_ascii=False,indent=2,default=str))
        print(ticker,funnel[-1],gap_summary[-1],active_summary[-1],flush=True)
    for name,values in [('funnel',funnel),('reason_counts',reason_rows),('phase1_gap_addendum',gap_summary),('timestamp_audit',timing),('active_summary',active_summary)]:
        write_csv(OUT/(name+'.csv'),values);(OUT/(name+'.json')).write_text(json.dumps(values,ensure_ascii=False,indent=2,default=str))
    (OUT/'blocked_triplets.json').write_text(json.dumps(blocked_details,indent=2))
    (OUT/'active_real_examples.json').write_text(json.dumps(examples,indent=2,default=str))
    assert all(x['extreme_matches_open'] and x['confirmation_matches_close'] and x['confirmation_matches_available'] for x in timing)
    print('TIMESTAMP AUDIT',len(timing),'PASS; ACTIVE middle-skip examples',len(examples),flush=True)
if __name__=='__main__':main()
