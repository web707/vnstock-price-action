import copy,json,unittest
import pandas as pd
from phase4_tests.test_phase4 import fixture,T,STREAM
from structure_builder_sfs.phase4 import canonical
from reversal_setup_detector.context import ContextProvider,phase2_rules
from reversal_setup_detector import analyze,Calendar
from reversal_setup_detector.tools.report_phase1 import load_rows
from reversal_setup_detector.tools.report_phase2 import events,SOURCE

def downs():return [dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN')]
def query(p,h=12):return p.evaluate(T(h),**STREAM)
class Phase2Tests(unittest.TestCase):
    def test_AT08_two_adjacent_major_downs_confirmed_available(self):
        z=query(ContextProvider(fixture(downs())))
        self.assertTrue(z['context_valid']);self.assertEqual(z['selected_ids'],['A','B']);self.assertEqual(z['reason_code'],'CONTEXT_TWO_ADJACENT_MAJOR_DOWNS_CONFIRMED')
    def test_AT09_invalid_context(self):
        cases=[([dict(id='A',hour=10,direction='DOWN')],12,'CONTEXT_NOT_ENOUGH_MAJOR_STRUCTURES'),
               ([dict(id='A',hour=10,direction='UP'),dict(id='B',hour=11,direction='DOWN')],12,'CONTEXT_NOT_TWO_ADJACENT_DOWNS'),
               ([dict(id='A',hour=10,direction='DOWN',broken=12),dict(id='B',hour=11,direction='DOWN')],12,'CONTEXT_STRUCTURE_BROKEN'),
               ([dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=13,direction='DOWN')],12,'CONTEXT_NOT_ENOUGH_MAJOR_STRUCTURES'),
               ([dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN',rejected=True)],12,'CONTEXT_NOT_ENOUGH_MAJOR_STRUCTURES')]
        for specs,at,reason in cases:
            with self.subTest(specs=specs):
                z=query(ContextProvider(fixture(specs)),at);self.assertFalse(z['context_valid']);self.assertEqual(z['reason_code'],reason)
    def test_no_skipping_UP_in_middle(self):
        z=query(ContextProvider(fixture(downs()+[dict(id='C',hour=11.5,direction='UP')])));self.assertEqual(z['selected_ids'],['B','C']);self.assertFalse(z['context_valid'])
    def test_no_skipping_BROKEN_between_active_pair(self):
        s=[dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN',broken=12),dict(id='C',hour=12,direction='DOWN')]
        z=query(ContextProvider(fixture(s)),13);self.assertEqual(z['selected_ids'],['B','C']);self.assertFalse(z['context_valid'])
    def test_INTERNAL_may_be_excluded_before_major_adjacency(self):
        s=[dict(id='A',hour=10,direction='DOWN'),dict(id='I',hour=10.5,direction='UP',ratio=2),dict(id='B',hour=11,direction='DOWN')]
        self.assertTrue(query(ContextProvider(fixture(s)))['context_valid'])
    def test_confirmation_exact_boundary_no_early_context(self):
        p=ContextProvider(fixture(downs()));self.assertFalse(query(p,11-1/3600)['context_valid']);self.assertTrue(query(p,11)['context_valid'])
    def test_break_exact_boundary_not_final_state_backfill(self):
        s=downs();s[0]['broken']=12;p=ContextProvider(fixture(s))
        self.assertTrue(query(p,12-1/3600)['context_valid']);self.assertFalse(query(p,12)['context_valid']);self.assertTrue(query(p,11.5)['context_valid'])
    def test_lookahead_append_future_confirmation_and_break(self):
        e=fixture(downs()+[dict(id='C',hour=14,direction='UP',broken=15)])
        prefix=e[e.available_at<=T(12)]
        self.assertEqual(query(ContextProvider(prefix)),query(ContextProvider(e)))
    def test_lookahead_future_payload_not_parsed(self):
        e=fixture(downs()+[dict(id='C',hour=14,direction='UP')]);expected=query(ContextProvider(e))
        e.loc[e.available_at>T(12),'payload_json']='NOT_JSON'
        self.assertEqual(query(ContextProvider(e)),expected)
    def test_context_available_at_not_end_time(self):
        p=ContextProvider(fixture(downs()));z=query(p,10.9);self.assertFalse(z['context_valid'])
        self.assertEqual(query(p,11)['context_available_at'],T(11).isoformat())
    def test_wrong_version_known_event_rejected(self):
        e=fixture(downs());e.loc[0,'rule_version']='wrong'
        with self.assertRaisesRegex(ValueError,'UPSTREAM_VERSION'):query(ContextProvider(e))
    def test_missing_history_rejected(self):
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_EVENT_HISTORY'):query(ContextProvider(fixture(downs()).iloc[1:]))
    def test_duplicate_events_exact_and_conflict(self):
        e=fixture(downs());p=query(ContextProvider(e));self.assertEqual(p,query(ContextProvider(pd.concat([e,e.iloc[:1]]))))
        other=e.iloc[:1].copy();other['reason_code']='changed'
        with self.assertRaisesRegex(ValueError,'CONFLICTING_EVENT'):query(ContextProvider(pd.concat([e,other])))
    def test_reverse_query_order_and_input_order(self):
        e=fixture(downs());p=ContextProvider(e.iloc[::-1]);query(p,15)
        self.assertEqual(query(p,10),query(ContextProvider(e),10))
    def test_no_mutation_and_defensive_output(self):
        e=fixture(downs());old=e.copy(deep=True);p=ContextProvider(e);z=query(p);z['structures'][0]['status']='BROKEN'
        self.assertTrue(query(p)['context_valid']);pd.testing.assert_frame_equal(e,old)
    def test_explicit_source_stream_isolation(self):
        e=pd.concat([fixture(downs()),fixture([dict(id='OTHER',hour=11.5,direction='UP',source='other')])]);self.assertTrue(query(ContextProvider(e))['context_valid'])
    def test_no_context_age_filter_allowed(self):
        from reversal_setup_detector import Rules
        c=phase2_rules().as_dict();c['max_context_age_bars']=100
        with self.assertRaisesRegex(ValueError,'CONTEXT_AGE_FILTER_NOT_ALLOWED'):ContextProvider([],Rules(c))
    def test_d04_deferred_and_approved_decisions(self):
        r=phase2_rules();self.assertTrue(r.get('allow_cross_session_sequences'));d=r.get('decision_status')
        self.assertEqual(d,{'L3-D01':'APPROVED','L3-D02':'APPROVED','L3-D03':'CONDITIONALLY_APPROVED','L3-D04':'DEFERRED','L3-D05':'APPROVED'})
    def test_layer2_long_fields_stay_null(self):
        from structure_builder_sfs.phase4 import MajorContext
        p=ContextProvider(fixture(downs()));s=p.snapshot(T(12),**STREAM);z=MajorContext([],p.upstream).context_from_snapshot(s,mode='EVER_CONFIRMED')
        self.assertIsNone(z['is_long_candidate']);self.assertEqual(z['reason_code'],'LONG_CONTEXT_NOT_EVALUATED')

class Phase2RealTests(unittest.TestCase):
    def test_real_context_history_prefix_at_every_event_boundary(self):
        for ticker in ['HPG','FPT','VNM','VCB','SSI']:
            e=events(ticker);times=pd.to_datetime(e.available_at);p=ContextProvider(e);stream=dict(ticker=ticker,timeframe='15m',source_version=SOURCE);n=0
            for at in sorted(set(times)):
                for cutoff in [at-pd.Timedelta(seconds=1),at]:
                    self.assertEqual(p.evaluate(cutoff,**stream),ContextProvider(e[times<=cutoff]).evaluate(cutoff,**stream));n+=1
            print('REAL_CONTEXT_PREFIX',ticker,n,'event-boundary comparisons PASS',flush=True)
    def test_real_timestamp_and_no_one_bar_lookahead(self):
        from reversal_setup_detector.tools.report_phase2 import ROOT
        from swing_detector.detector import detect_result
        from swing_detector.config import SwingDetectorConfig
        r=phase2_rules();total=0
        for ticker in ['HPG','FPT','VNM','VCB','SSI']:
            b=pd.read_csv(ROOT/f'reports/layer1/{ticker}_clean.csv');s=pd.read_csv(ROOT/f'reports/layer1_schema/{ticker}.csv')
            for row in s.to_dict('records'):
                self.assertEqual(r.timestamp(row['extreme_time']),r.timestamp(b.iloc[int(row['index'])].Datetime))
                at=r.timestamp(row['confirmed_at']);bar=b.iloc[int(row['confirmed_at_index'])]
                self.assertEqual(at,r.timestamp(bar.Datetime)+r.duration);self.assertEqual(at,r.timestamp(bar.available_time));total+=1
            row=s.iloc[0];at=r.timestamp(row.confirmed_at);cfg=SwingDetectorConfig(ticker=ticker)
            before=detect_result(b,cfg,as_of=at-pd.Timedelta(seconds=1));after=detect_result(b,cfg,as_of=at)
            self.assertFalse(any(pd.Timestamp(x)==at for x in before.swings.confirmed_at));self.assertTrue(any(pd.Timestamp(x)==at for x in after.swings.confirmed_at))
            cal=Calendar.template(r,'2026-08-07 00:00+07:00','2026-10-29 00:00+07:00');data=load_rows(ticker)
            z=analyze(data,r,cal,as_of=at-pd.Timedelta(seconds=1));zz=analyze(data,r,cal,as_of=at)
            self.assertEqual(len(zz['candles']),len(z['candles'])+1)
        print('REAL_TIMESTAMP',total,'swings index/time joins + 5 Layer1/Layer3 exact-close boundaries PASS',flush=True)
    def test_real_funnel_and_ACTIVE_middle_skip_evidence(self):
        from reversal_setup_detector.tools.report_phase2 import OUT
        f=json.loads((OUT/'funnel.json').read_text());self.assertEqual(sum(x['candle_times'] for x in f),4482)
        self.assertEqual(sum(x['red_triplets'] for x in f),25)
        for x in f:self.assertEqual(x['red_triplets'],x['triplets_with_context']+x['triplets_context_rejected'])
        examples=json.loads((OUT/'active_real_examples.json').read_text());self.assertGreater(len(examples),0)
        for x in examples:
            a,b=[r['structure_sequence_no'] for r in x['active']]
            self.assertTrue(all(a<r['structure_sequence_no']<b and r['status']=='BROKEN' for r in x['skipped_broken_between']))
            self.assertNotEqual([r['structure_id'] for r in x['ever_confirmed']],[r['structure_id'] for r in x['active']])
        print('REAL_ACTIVE',len(examples),'unique pair examples with BROKEN strictly between ACTIVE pair PASS',flush=True)
    def test_real_phase1_gap_addendum_reconciles(self):
        from reversal_setup_detector.tools.report_phase2 import OUT
        rows=json.loads((OUT/'phase1_gap_addendum.json').read_text())
        for x in rows:self.assertEqual(x['morphology_before_gap'],x['blocked_suspected_gap']+x['valid_triplets'])
        self.assertEqual(sum(x['valid_triplets'] for x in rows),25)
