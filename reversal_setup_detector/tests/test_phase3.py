"""AT10–AT18: explicit SYNTHETIC boundary fixtures + REAL-SNAPSHOT audits.
No tests write SQL or emit LONG_SETUP.
"""
import copy
import json
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from decimal import Decimal
from reversal_setup_detector.candles import Calendar,Rules
from reversal_setup_detector.calendar_phase3 import (empirical_calendar,audit_rows,HOLIDAYS_IN_SNAPSHOT,
    DAILY_OPEN_TIMES,EXCEPTIONAL_OBSERVED_SLOTS)
from reversal_setup_detector.context import ContextProvider
from reversal_setup_detector.lifecycle import scan_lifecycle
from reversal_setup_detector.tools.report_phase1 import load_rows
from reversal_setup_detector.tools.report_phase2 import events,SOURCE
from phase4_tests.test_phase4 import fixture,STREAM,T

ROOT=Path(__file__).resolve().parents[2]

def rules(cross=True):
    name='TRUE' if cross else 'FALSE'
    return Rules(json.loads((ROOT/f'reversal_setup_detector/config/L3_REVERSAL_V1_PHASE3_CROSS_{name}.json').read_text()))

def make_bar(hhmm,op,close,*,available_at=None,date='2026-01-05',ticker='TEST'):
    open_=Decimal(str(op));closing=Decimal(str(close))
    return dict(ticker=ticker,timeframe='15m',candle_time=f'{date}T{hhmm}:00+07:00',
                open=str(open_),high=str(max(open_,closing)),low=str(min(open_,closing)),close=str(closing),
                volume='100',available_at=available_at)

def synthetic_case(ratios=(),*,cross=True,break_at=None,late_g_at=None,missing=(),extra_red=False,drop_last=0):
    r=rules(cross)
    start=T(13);candles=[];slots=[]
    for i in range(12):
        t=start+timedelta(minutes=15*i)
        # At i=4 simulate a new exchange session if required by synthetic fixture.
        session='PM1' if i<4 else 'PM2'
        slots.append(dict(open_at=t,close_at=t+timedelta(minutes=15),session_id=session if drop_last else 'PM1'))
    # The normal (non-drop_last) fixture is one same-session window.
    cal=Calendar(slots,r,calendar_id='SYNTHETIC_AT10_AT18',verified=True,
                 coverage_start=T(12),coverage_end=T(18))
    starts=['13:00','13:15','13:30']
    candles.extend([make_bar(starts[0],120,110),make_bar(starts[1],110,109),make_bar(starts[2],110,100)])
    for i,ratio in enumerate(ratios[:5]):
        t=start+timedelta(minutes=15*(i+3))
        hm=t.strftime('%H:%M')
        if i in missing:continue
        if ratio is None:bar=make_bar(hm,110,110)  # DOJI
        elif ratio=='RED':bar=make_bar(hm,110,109)
        else:bar=make_bar(hm,100,Decimal('100')+Decimal(str(ratio))*10)
        if i==0 and late_g_at:bar['available_at']=late_g_at
        candles.append(bar)
    specs=[dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN')]
    if break_at is not None:specs[1]['broken']=break_at
    provider=ContextProvider(fixture(specs),rules=r)
    return r,cal,candles,provider

def run(case,as_of=T(17)):
    r,cal,bars,provider=case
    return scan_lifecycle(bars,r,cal,provider,as_of=as_of,
       ticker='TEST',timeframe='15m',source_version='fixture-v1')

class Phase3AcceptanceSynthetic(unittest.TestCase):
    def one(self,case,at=T(17)):
        z=run(case,at)
        self.assertEqual(len(z['candidates']),1)
        return z['candidates'][0],z
    def test_AT10_ratio_below_one_rejected(self):
        s,z=self.one(synthetic_case([Decimal('0.999999'),None,None,None,None]))
        self.assertEqual(s['status'],'EXPIRED')
        self.assertEqual(s['window_checks'][0]['reason_code'],'REVERSAL_BODY_RATIO_TOO_SMALL')
    def test_AT11_ratio_equal_one_found(self):
        s,z=self.one(synthetic_case([Decimal('1.0')]))
        self.assertEqual(s['status'],'FOUND');self.assertEqual(s['body_ratio'],'1.0')
    def test_AT12_ratio_strictly_inside_found(self):
        s,z=self.one(synthetic_case([Decimal('1.5')]))
        self.assertEqual(s['status'],'FOUND');self.assertEqual(s['body_ratio'],'1.5')
    def test_AT13_ratio_equal_two_found(self):
        s,z=self.one(synthetic_case([Decimal('2.0')]))
        self.assertEqual(s['status'],'FOUND');self.assertEqual(s['body_ratio'],'2.0')
    def test_AT14_ratio_above_two_rejected(self):
        s,z=self.one(synthetic_case([Decimal('2.000001'),None,None,None,None]))
        self.assertEqual(s['status'],'EXPIRED')
        self.assertEqual(s['window_checks'][0]['reason_code'],'REVERSAL_BODY_RATIO_TOO_LARGE')
    def test_AT15_first_green_after_R3_found(self):
        s,z=self.one(synthetic_case([Decimal('1.4')]))
        self.assertEqual(s['bars_checked'],1)
        self.assertEqual(s['reversal_candle_time'][-14:-6],'13:45:00')
        self.assertEqual(len([e for e in z['events'] if e['event_type']=='REVERSAL_FOUND']),1)
    def test_AT16_green_fifth_after_R3_found(self):
        s,z=self.one(synthetic_case([None,Decimal('0.5'),'RED',Decimal('2.5'),Decimal('2.0')]))
        self.assertEqual(s['bars_checked'],5)
        self.assertEqual(s['status'],'FOUND')
        self.assertEqual(s['reversal_candle_time'][-14:-6],'14:45:00')
    def test_AT17_expire_after_exact_five(self):
        case=synthetic_case([None,None,None,None,None])
        early,z=self.one(case,T(14.75))
        self.assertEqual(early['status'],'WAITING_REVERSAL');self.assertEqual(early['bars_checked'],4)
        late,z=self.one(case,T(15))
        self.assertEqual(late['status'],'EXPIRED');self.assertEqual(late['bars_checked'],5)
        self.assertEqual(late['resolved_at'],T(15).isoformat())
    def test_AT18_no_lookahead_until_close_and_source_available(self):
        case=synthetic_case([Decimal('1.5')],late_g_at=T(14.1).isoformat())
        s,z=self.one(case,T(14))
        self.assertEqual(s['status'],'WAITING_REVERSAL')
        s,z=self.one(case,T(14.09))
        self.assertEqual(s['status'],'WAITING_REVERSAL')
        s,z=self.one(case,T(14.1))
        self.assertEqual(s['status'],'FOUND');self.assertEqual(s['found_at'],T(14.1).isoformat())
    def test_context_break_at_same_G_close_wins(self):
        s,z=self.one(synthetic_case([Decimal('1.0')],break_at=14))
        self.assertEqual(s['status'],'INVALIDATED')
        self.assertEqual(s['reason_code'],'CONTEXT_STRUCTURE_BROKEN')
        self.assertEqual(s['resolved_at'],T(14).isoformat())
        self.assertIsNone(s['reversal_candle_time'])
    def test_context_break_after_found_does_not_retroactively_invalidate(self):
        s,z=self.one(synthetic_case([Decimal('1.0')],break_at=14+1/3600))
        self.assertEqual(s['status'],'FOUND')
    def test_context_break_between_candles_is_recorded_when_known(self):
        s,z=self.one(synthetic_case([None,Decimal('1.0')],break_at=14.1))
        self.assertEqual(s['status'],'INVALIDATED')
        self.assertEqual(s['resolved_at'],T(14.1).isoformat())
    def test_gap_cannot_skip_missing_window_candle(self):
        s,z=self.one(synthetic_case([None,None,None,None,None],missing=(1,)))
        self.assertEqual(s['status'],'INVALIDATED')
        self.assertEqual(s['reason_code'],'DATA_GAP_IN_CANDLE_SEQUENCE')
        self.assertEqual(s['bars_checked'],1)
    def test_r3_is_not_green_window_first_bar(self):
        s,z=self.one(synthetic_case([]),T(13.75))
        self.assertEqual(s['status'],'WAITING_REVERSAL')
        self.assertEqual(s['bars_checked'],0)
    def test_deterministic_replay_idempotent(self):
        case=synthetic_case([Decimal('1.5')]);self.assertEqual(run(case),run(case))
        s,z=self.one(case);self.assertEqual(len(z['candidates']),1)
    def test_overlapping_red_triplets_distinct(self):
        case=synthetic_case(['RED',Decimal('1.5')]);case[2][3]=make_bar('13:45',110,100)
        z=run(case)
        self.assertEqual(len(z['candidates']),2)
        self.assertNotEqual(z['candidates'][0]['setup_id'],z['candidates'][1]['setup_id'])
    def test_cross_session_disabled_blocks_window(self):
        case=synthetic_case([None,None,None,None,None],cross=False,drop_last=1)
        s,z=self.one(case)
        self.assertTrue(s['window_crosses_session'])
        self.assertEqual(s['status'],'INVALIDATED')
        self.assertEqual(s['reason_code'],'CROSS_SESSION_WINDOW_BLOCKED')

class Phase3RealSnapshot(unittest.TestCase):
    def test_real_calendar_slot_distribution_and_exchange_holiday(self):
        for ticker in ['HPG','FPT','VNM','VCB','SSI']:
            r=rules();rows=load_rows(ticker);calendar=empirical_calendar(r,ticker)
            a=audit_rows(rows,ticker,calendar,r)
            self.assertEqual(a['trading_days'],56)
            self.assertEqual(a['missing_expected_slots'],[])
            self.assertEqual(a['unexpected_slots'],[])
            self.assertEqual(a['duplicate_times'],[])
            self.assertEqual(a['time_slot_counts']['09:00'],0)
            self.assertEqual(a['time_slot_counts']['14:45'],56)
            for hm in DAILY_OPEN_TIMES:self.assertEqual(a['time_slot_counts'][hm],56)
            self.assertEqual(a['time_slot_counts']['14:30'],1 if ticker in ('VCB','SSI') else 0)
            self.assertFalse(calendar.verified)
            self.assertEqual(a['daily_count_distribution'],{16:56} if ticker not in ('VCB','SSI') else {16:55,17:1})
            self.assertTrue(all(x['date'] not in HOLIDAYS_IN_SNAPSHOT for x in a['daily_counts']))
    def test_real_four_candidate_true_policy_and_false_comparison(self):
        actual={}
        for flag in (True,False):
            by_ticker={}
            r=rules(flag)
            for ticker in ['HPG','FPT','VNM','VCB','SSI']:
                bars=load_rows(ticker);cal=empirical_calendar(r,ticker)
                z=scan_lifecycle(bars,r,cal,ContextProvider(events(ticker),rules=r),
                    as_of=cal.end,ticker=ticker,timeframe='15m',source_version=SOURCE)
                by_ticker[ticker]=z
                self.assertEqual(z['metrics']['invalid_candles'],0)
                self.assertEqual(z['metrics']['data_gaps'],0)
            actual[flag]=by_ticker
        a=actual[True]
        self.assertEqual([len(a[t]['candidates']) for t in ['HPG','FPT','VNM','VCB','SSI']],[1,2,0,0,1])
        self.assertEqual([(s['status'],s['reason_code'],s['window_crosses_session']) for s in a['HPG']['candidates']], [('INVALIDATED','CONTEXT_STRUCTURE_BROKEN',True)])
        self.assertEqual([s['status'] for s in a['FPT']['candidates']],['EXPIRED','FOUND'])
        self.assertEqual([(s['status'],s['bars_checked'],s['window_crosses_session']) for s in a['SSI']['candidates']],[('FOUND',5,True)])
        self.assertEqual(a['SSI']['candidates'][0]['reversal_candle_time'][:16],'2026-10-16T09:15')
        b=actual[False]
        self.assertEqual([len(b[t]['candidates']) for t in ['HPG','FPT','VNM','VCB','SSI']],[1,1,0,0,1])
        self.assertEqual([x['status'] for x in b['FPT']['candidates']],['FOUND'])
        self.assertEqual([x['reason_code'] for x in b['SSI']['candidates']],['CROSS_SESSION_WINDOW_BLOCKED'])
        self.assertEqual([x['reason_code'] for x in b['HPG']['candidates']],['CONTEXT_STRUCTURE_BROKEN'])
    def test_real_HPG_BROKEN_at_same_time_as_G_and_SSI_unbroken(self):
        r=rules()
        for t,at,expected in [('HPG','2026-10-05T09:30:00+07:00',False),('SSI','2026-10-16T09:30:00+07:00',True)]:
            provider=ContextProvider(events(t),rules=r)
            result=provider.evaluate(at,ticker=t,timeframe='15m',source_version=SOURCE)
            self.assertEqual(result['context_valid'],expected)
            if t=='HPG':self.assertEqual(result['reason_code'],'CONTEXT_STRUCTURE_BROKEN')

if __name__=='__main__':unittest.main()
