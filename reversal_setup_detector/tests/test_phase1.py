import copy
import csv
import json
import unittest
from datetime import timedelta
from pathlib import Path
from reversal_setup_detector import Rules, Calendar, analyze, morphology
ROOT=Path(__file__).resolve().parents[2]

def row(time='2026-10-26 09:00:00+07:00', **kw):
    d=dict(ticker='HPG',timeframe='15m',candle_time=time,open=110,high=111,low=99,close=100,volume=0)
    d.update(kw);return d

def three():
    return [row(f'2026-10-26 {t}:00+07:00') for t in ['09:00','09:15','09:30']]

def calendar(r=None):
    r=r or Rules();c=Calendar.template(r,'2026-10-23 00:00+07:00','2026-10-28 00:00+07:00')
    return Calendar(c.slots,r,calendar_id='EXPLICIT_TEST_FIXTURE',verified=True,coverage_start=c.start,coverage_end=c.end)

def scan(rows,r=None,cal=None,at='2026-10-26 15:00+07:00'):
    r=r or Rules();return analyze(rows,r,cal or calendar(r),as_of=at)

class AcceptanceTests(unittest.TestCase):
    def test_AT01_red(self): self.assertEqual(morphology(row())['color'],'RED')
    def test_AT02_green(self): self.assertEqual(morphology(row(open=100,close=110))['color'],'GREEN')
    def test_AT03_doji(self): self.assertEqual(morphology(row(open=100,close=100))['color'],'DOJI')
    def test_AT04_R1_strict_body_wick(self):
        for high,expected in [(111,1),(119,0),(120,0)]:
            x=three();x[0]['high']=high;self.assertEqual(len(scan(x)['triplets']),expected)
    def test_AT05_R2_no_strength_required(self):
        x=three();x[1].update(high=150,low=50);self.assertEqual(len(scan(x)['triplets']),1)
    def test_AT06_R3_strict_body_wick(self):
        for high,expected in [(111,1),(119,0),(120,0)]:
            x=three();x[2]['high']=high;self.assertEqual(len(scan(x)['triplets']),expected)
    def test_AT07_contiguous_red_and_barriers(self):
        self.assertEqual(len(scan(three())['triplets']),1)
        for change in [dict(open=100,close=110),dict(close=110),dict(high=1)]:
            x=three();x[1].update(change);x.append(row('2026-10-26 09:45+07:00'))
            self.assertEqual(scan(x)['triplets'],[])
    def test_AT21_verified_missing_candle_blocks_sequence(self):
        x=three();x[2]['candle_time']='2026-10-26 09:45+07:00'
        r=scan(x);self.assertEqual(r['triplets'],[]);self.assertEqual(r['gaps'][0]['reason_code'],'DATA_GAP_IN_CANDLE_SEQUENCE')
        self.assertEqual(r['gaps'][0]['missing_times'],['2026-10-26T09:30:00+07:00'])

class EdgeTests(unittest.TestCase):
    def test_exact_decimal_wicks_and_equality(self):
        x=morphology(row(open='0.3',close='0.2',high='0.35',low='0.15'))
        self.assertEqual(str(x['body']),'0.1');self.assertEqual(str(x['total_wick']),'0.10');self.assertFalse(x['strong'])
    def test_invalid_values_are_barriers_not_repaired(self):
        for bad in [dict(open=None),dict(high=float('inf')),dict(low=-1),dict(volume=-1),dict(volume=None),dict(close=200),dict(low=112),dict(open=True)]:
            x=three();x[1].update(bad);z=scan(x)
            self.assertEqual(z['triplets'],[]);self.assertEqual(z['metrics']['invalid_candles'],1)
    def test_missing_stream_identity_fails_contract(self):
        for key in ['ticker','timeframe']:
            x=row();x[key]=None
            with self.assertRaisesRegex(ValueError,'STREAM_IDENTITY_REQUIRED'):scan([x])
    def test_malformed_timestamp_fails_contract(self):
        with self.assertRaises(ValueError):scan([row('not-a-time')])
    def test_duplicates_quarantine_all(self):
        x=three();x.append(copy.deepcopy(x[1]));z=scan(x)
        self.assertEqual(z['metrics']['invalid_candles'],2);self.assertFalse(z['triplets'])
    def test_future_duplicate_does_not_change_past(self):
        x=three();z=scan(x);x.append(dict(x[1],available_at='2026-10-27 10:00+07:00'))
        self.assertEqual(scan(x),z)
    def test_unsorted_input_sorted_without_mutation(self):
        x=three()[::-1];before=copy.deepcopy(x);self.assertEqual(scan(x),scan(three()));self.assertEqual(x,before)
    def test_streams_do_not_mix(self):
        x=three();x[1]['ticker']='FPT';self.assertFalse(scan(x)['triplets'])
    def test_wrong_timeframe_invalid(self):
        x=three();x[1]['timeframe']='5m';self.assertFalse(scan(x)['triplets'])
    def test_availability_requires_close_and_source(self):
        x=three();x[-1]['available_at']='2026-10-26 09:31+07:00'
        self.assertFalse(scan(x,at='2026-10-26 09:44+07:00')['triplets'])
        self.assertEqual(len(scan(x,at='2026-10-26 09:45+07:00')['triplets']),1)
        x[-1]['available_at']='2026-10-26 10:00+07:00'
        self.assertFalse(scan(x,at='2026-10-26 09:45+07:00')['triplets'])
        self.assertEqual(scan(x,at='2026-10-26 10:00+07:00')['triplets'][0]['available_at'],'2026-10-26T10:00:00+07:00')
    def test_late_R2_is_barrier_until_available(self):
        x=three();x[1]['available_at']='2026-10-26 10:00+07:00'
        self.assertFalse(scan(x,at='2026-10-26 09:45+07:00')['triplets'])
        self.assertEqual(scan(x,at='2026-10-26 10:00+07:00')['triplets'][0]['available_at'],'2026-10-26T10:00:00+07:00')
    def test_future_mutation_prefix_equivalence(self):
        x=three();past=scan(x,at='2026-10-26 09:45+07:00')
        x.append(row('2026-10-26 10:00+07:00',high=-100))
        self.assertEqual(scan(x,at='2026-10-26 09:45+07:00'),past)
    def test_lunch_crossing_allowed_and_variant_blocked(self):
        x=[row(f'2026-10-26 {t}+07:00') for t in ['11:00','11:15','13:00']]
        z=scan(x);self.assertTrue(z['triplets'][0]['cross_session']);self.assertFalse(z['gaps'])
        c=Rules().as_dict();c.update(rule_version='L3_REVERSAL_NO_CROSS_TEST',allow_cross_session_sequences=False)
        self.assertFalse(scan(x,Rules(c))['triplets'])
    def test_overnight_weekend_not_data_gap_with_explicit_calendar(self):
        x=[row('2026-10-23 14:30+07:00'),row('2026-10-23 14:45+07:00'),row('2026-10-26 09:00+07:00')]
        z=scan(x);self.assertEqual(len(z['triplets']),1);self.assertFalse(z['gaps']);self.assertTrue(z['triplets'][0]['cross_date'])
    def test_holiday_absence_only_when_calendar_says_closed(self):
        r=Rules();c=calendar(r);slots=[x for x in c.slots if str(x['open_at'].date())!='2026-10-26']
        c=Calendar(slots,r,calendar_id='HOLIDAY_FIXTURE',verified=True,coverage_start=c.start,coverage_end=c.end)
        x=[row('2026-10-23 14:30+07:00'),row('2026-10-23 14:45+07:00'),row('2026-10-27 09:00+07:00')]
        self.assertEqual(len(scan(x,cal=c,at='2026-10-27 09:15+07:00')['triplets']),1)
    def test_unverified_template_gap_not_claimed_verified(self):
        r=Rules();c=Calendar.template(r,'2026-10-26 00:00+07:00','2026-10-27 00:00+07:00');x=three();x[2]['candle_time']='2026-10-26 09:45+07:00'
        z=scan(x,cal=c);self.assertFalse(z['triplets']);self.assertEqual(z['gaps'][0]['reason_code'],'UNVERIFIED_CALENDAR_GAP')
    def test_off_grid_candle_blocks_adjacent_pattern(self):
        x=three();x.insert(1,row('2026-10-26 09:07+07:00'));self.assertFalse(scan(x)['triplets'])
    def test_calendar_coverage_is_required(self):
        with self.assertRaisesRegex(ValueError,'AS_OF_OUTSIDE_CALENDAR_COVERAGE'):scan(three(),at='2026-10-30 09:00+07:00')
    def test_calendar_overlap_rejected(self):
        r=Rules();c=calendar(r)
        with self.assertRaisesRegex(ValueError,'OVERLAPPING'):Calendar(c.slots+[c.slots[0]],r,calendar_id='bad',verified=True,coverage_start=c.start,coverage_end=c.end)
    def test_actual_close_from_explicit_auction_slot(self):
        r=Rules();c=Calendar([dict(open_at='2026-10-26 14:30+07:00',close_at='2026-10-26 14:40+07:00',session_id='AUCTION_FIXTURE')],r,calendar_id='SHORT_BAR_FIXTURE',verified=True,coverage_start='2026-10-26 00:00+07:00',coverage_end='2026-10-27 00:00+07:00')
        z=scan([row('2026-10-26 14:30+07:00')],cal=c,at='2026-10-26 14:40+07:00')
        self.assertEqual(len(z['candles']),1);self.assertEqual(z['candles'][0]['available_at'],'2026-10-26T14:40:00+07:00')
    def test_config_new_version_required(self):
        c=Rules().as_dict();c['allow_cross_session_sequences']=False
        with self.assertRaisesRegex(ValueError,'NEW_RULE_VERSION_REQUIRED'):Rules(c)
    def test_config_is_immutable_copy(self):
        r=Rules();c=r.as_dict();c['decision_status']['L3-D01']='APPROVED';self.assertEqual(r.get('decision_status')['L3-D01'],'PROPOSED')
    def test_invalid_window_config_rejected(self):
        c=Rules().as_dict();c.update(rule_version='BAD_WINDOW',max_wait_candles=0)
        with self.assertRaisesRegex(ValueError,'POSITIVE_WINDOW_REQUIRED'):Rules(c)
    def test_template_cannot_assert_verified(self):
        c=Rules().as_dict();c['rule_version']='BAD_CALENDAR';c['calendar_template']['verified']=True
        with self.assertRaisesRegex(ValueError,'TEMPLATE_CANNOT'):Rules(c)
    def test_calendar_binding_mismatch_rejected(self):
        c=Rules().as_dict();c.update(rule_version='L3_5M_BINDING',timeframe='5m');r=Rules(c)
        with self.assertRaisesRegex(ValueError,'CALENDAR_RULE_BINDING_MISMATCH'):scan(three(),r,calendar())
    def test_timeframe_configurable(self):
        c=Rules().as_dict();c.update(rule_version='L3_TEST_5M',timeframe='5m');r=Rules(c)
        x=[row(f'2026-10-26 09:{m:02d}+07:00',timeframe='5m') for m in [0,5,10]]
        self.assertEqual(len(scan(x,r)['triplets']),1)
    def test_close_label_configurable(self):
        c=Rules().as_dict();c.update(rule_version='L3_TEST_CLOSE',timestamp_label='close');r=Rules(c)
        x=[row(f'2026-10-26 09:{m:02d}+07:00') for m in [15,30,45]]
        self.assertEqual(scan(x,r,at='2026-10-26 09:45+07:00')['triplets'][0]['available_at'],'2026-10-26T09:45:00+07:00')
    def test_overlapping_triplets_retained_no_setup_created(self):
        x=three()+[row('2026-10-26 09:45+07:00')];z=scan(x)
        self.assertEqual(len(z['triplets']),2);self.assertNotEqual(z['triplets'][0]['pattern_id'],z['triplets'][1]['pattern_id']);self.assertNotIn('setups',z)
    def test_deterministic_repeat(self):self.assertEqual(scan(three()),scan(three()))
    def test_layer2_ACTIVE_skips_BROKEN_read_only(self):
        from structure_builder_sfs.phase4 import MajorContext
        ctx=MajorContext([]);snapshot=dict(snapshot_id='test',ticker='HPG',timeframe='15m',source_version='test',as_of_time='2026-10-26',rule_version=ctx.rules.version,upstream_rule_version=ctx.rules.get('upstream_rule_version'),config_hash=ctx.rules.config_hash,major_sequence=[dict(structure_id=k,status=v) for k,v in [('A','CONFIRMED'),('B','BROKEN'),('C','CONFIRMED')]])
        self.assertEqual([x['structure_id'] for x in ctx.context_from_snapshot(snapshot,mode='EVER_CONFIRMED')['structures']],['B','C'])
        self.assertEqual([x['structure_id'] for x in ctx.context_from_snapshot(snapshot,mode='ACTIVE')['structures']],['A','C'])

class RealSnapshotTests(unittest.TestCase):
    def test_five_tickers_validation_and_prefix(self):
        from reversal_setup_detector.tools.report_phase1 import load_rows
        r=Rules();cal=Calendar.template(r,'2026-08-07 00:00+07:00','2026-10-29 00:00+07:00')
        for ticker in ['HPG','FPT','VNM','VCB','SSI']:
            rows=load_rows(ticker);z=analyze(rows,r,cal,as_of=cal.end)
            self.assertEqual(z['metrics']['invalid_candles'],0)
            for fraction in [.25,.5,.75]:
                at=r.timestamp(rows[int(len(rows)*fraction)]['available_at'])
                prefix=[x for x in rows if r.timestamp(x['available_at'])<=at]
                self.assertEqual(analyze(rows,r,cal,as_of=at),analyze(prefix,r,cal,as_of=at))
            for p in z['triplets']:
                self.assertEqual(p['available_at'],max(x['available_at'] for x in p['candles']))
            print('REAL',ticker,z['metrics'],'3 prefix comparisons PASS',flush=True)
    def test_spec_part_B_byte_copy(self):
        p=(ROOT/'reversal_setup_detector/source/PROMPT_LAYER3_VA_SPEC.md').read_bytes()
        self.assertEqual((ROOT/'docs/SPEC_LAYER3_v1.0.md').read_bytes(),p[p.index('# PHẦN B'.encode()):])
