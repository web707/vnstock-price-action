"""Phase4: AT19/20/22 synthetic + real replay/persistence acceptance tests.
All DBs in this suite are temporary sidecars; no upstream database is touched.
"""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from decimal import Decimal
from datetime import timedelta
from reversal_setup_detector.candles import Calendar
from reversal_setup_detector.phase4_config import ApprovedRules
from reversal_setup_detector.persistence import connect,persist_batch,export_long_setups,statistics
from reversal_setup_detector.lifecycle import scan_lifecycle
from reversal_setup_detector.calendar_phase3 import empirical_calendar
from reversal_setup_detector.context import ContextProvider
from reversal_setup_detector.tools.report_phase1 import load_rows
from reversal_setup_detector.tools.report_phase2 import events,SOURCE
from reversal_setup_detector.tests.test_phase3 import synthetic_case,make_bar
from phase4_tests.test_phase4 import fixture,T

TICKERS=('HPG','FPT','VNM','VCB','SSI')

def real_one(ticker,as_of=None):
    r=ApprovedRules();cal=empirical_calendar(r,ticker)
    return scan_lifecycle(load_rows(ticker),r,cal,ContextProvider(events(ticker),rules=r),
        as_of=as_of or cal.end,ticker=ticker,timeframe='15m',source_version=SOURCE)

def synthetic_one(ratios=(),*,overlap=False,break_at=None):
    old=synthetic_case(ratios,break_at=break_at)
    r=ApprovedRules();oldcal=old[1];rows=copy.deepcopy(old[2]);
    if overlap:rows[3]=make_bar('13:45',110,100)
    cal=Calendar(oldcal.slots,r,calendar_id='SYNTHETIC_PHASE4_15M',verified=True,
                 coverage_start=oldcal.start,coverage_end=oldcal.end)
    sp=[dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN')]
    if break_at is not None:sp[-1]['broken']=break_at
    provider=ContextProvider(fixture(sp),rules=r)
    return scan_lifecycle(rows,r,cal,provider,as_of=T(17),ticker='TEST',timeframe='15m',source_version='fixture-v1')

class Phase4SyntheticAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=connect(Path(self.temp.name)/'test.sqlite');self.addCleanup(self.db.close)
    def test_AT19_repeat_exact_same_data_rule_version_no_duplicate(self):
        z=synthetic_one([Decimal('1.5')]);one=persist_batch(self.db,[z]);before=list(self.db.execute('SELECT * FROM reversal_setup'))
        two=persist_batch(self.db,[z]);after=list(self.db.execute('SELECT * FROM reversal_setup'))
        self.assertEqual((one['inserted'],one['events_inserted']), (1,2))
        self.assertEqual((two['inserted'],two['events_inserted'],two['duplicates_prevented'],two['events_duplicates']),(0,0,1,2))
        self.assertEqual([tuple(x) for x in before],[tuple(x) for x in after])
        self.assertEqual(statistics(self.db)['setups'],1)
    def test_AT20_LONG_SETUP_only_after_green_close_and_source_available(self):
        # Synthetic data source available 14:06, while candle closes at 14:00:
        case=synthetic_case([Decimal('1.5')],late_g_at=T(14.1).isoformat())
        r=ApprovedRules();oldcal=case[1]
        cal=Calendar(oldcal.slots,r,calendar_id='SYNTHETIC_AT20',verified=True,
                     coverage_start=oldcal.start,coverage_end=oldcal.end)
        provider=ContextProvider(fixture([dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN')]),rules=r)
        def at(h):return scan_lifecycle(case[2],r,cal,provider,as_of=T(h),ticker='TEST',timeframe='15m',source_version='fixture-v1')
        early=at(14.09);first=persist_batch(self.db,[early]);self.assertEqual(len(export_long_setups(self.db)),0)
        late=at(14.1);second=persist_batch(self.db,[late]);signals=export_long_setups(self.db)
        self.assertEqual((first['inserted'],second['updated'],len(signals)),(1,1,1))
        self.assertEqual(signals[0]['signal_available_at'],T(14.1).isoformat())
        self.assertEqual(signals[0]['signal_time'],T(13.75).isoformat())
        self.assertEqual(signals[0]['reason_code'],'REVERSAL_PATTERN_FOUND')
        for forbidden in ('entry_price','fill_price','order_id','take_profit','stop_loss'):
            self.assertNotIn(forbidden,signals[0])
    def test_AT22_overlapping_different_R1_allowed_same_triple_not_duplicated(self):
        z=synthetic_one(['RED',Decimal('1.5')],overlap=True)
        self.assertEqual(len(z['candidates']),2)
        self.assertNotEqual(z['candidates'][0]['red_candle_times'][0],z['candidates'][1]['red_candle_times'][0])
        persist_batch(self.db,[z]);persist_batch(self.db,[z]);self.assertEqual(statistics(self.db)['setups'],2)
        self.assertEqual(self.db.execute('SELECT COUNT(DISTINCT red_candle_1_time) FROM reversal_setup').fetchone()[0],2)
    def test_sql_unique_natural_key_prevents_different_id(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z]);evil=copy.deepcopy(z)
        evil['candidates'][0]['setup_id']='FAKE-ID';evil['events']=[]
        with self.assertRaisesRegex(ValueError,'NATURAL_KEY_ID_COLLISION'):persist_batch(self.db,[evil])
        self.assertEqual(statistics(self.db)['setups'],1)
    def test_atomic_rollback_on_conflicting_context(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z]);modified=copy.deepcopy(z)
        modified['candidates'][0]['context_structure_ids']=['FAKE','B']
        with self.assertRaisesRegex(ValueError,'IMMUTABLE_SETUP_FIELD_CONFLICT'):persist_batch(self.db,[modified])
        self.assertEqual(statistics(self.db)['events'],2)
    def test_no_silent_terminal_recomputation(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z]);modified=copy.deepcopy(z)
        modified['candidates'][0]['body_ratio']='1.75'
        with self.assertRaisesRegex(ValueError,'TERMINAL_RECOMPUTE_REQUIRES_NEW_VERSION'):persist_batch(self.db,[modified])
    def test_event_id_conflict_transaction_rolls_back(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z]);other=copy.deepcopy(z)
        other['events'][0]['payload']={'modified':'yes'}
        with self.assertRaisesRegex(ValueError,'CONFLICTING_EVENT_PAYLOAD'):persist_batch(self.db,[other])
        self.assertEqual(statistics(self.db)['events'],2)
    def test_prefix_replay_cannot_downgrade_terminal(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z]);early=copy.deepcopy(z)
        s=early['candidates'][0];s['status']='WAITING_REVERSAL';s['reason_code']='SETUP_CREATED';s['available_at']=s['setup_detected_at'];s['resolved_at']=None
        early['events']=early['events'][:1]
        persist_batch(self.db,[early]);self.assertEqual(statistics(self.db)['by_status'],{'FOUND':1})
    def test_invalidated_at_same_green_available_wins_and_no_signal(self):
        z=synthetic_one([Decimal('1.0')],break_at=14)
        self.assertEqual(z['candidates'][0]['status'],'INVALIDATED')
        persist_batch(self.db,[z]);self.assertEqual(len(export_long_setups(self.db)),0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reversal_setup_event WHERE event_type='INVALIDATED'").fetchone()[0],1)
    def test_idempotent_even_with_reversed_results_order(self):
        z=synthetic_one(['RED',Decimal('1.5')],overlap=True)
        persist_batch(self.db,[z]);reverse=copy.deepcopy(z);reverse['candidates'].reverse();reverse['events'].reverse()
        out=persist_batch(self.db,[reverse]);self.assertEqual(out['inserted'],0)
        self.assertEqual(statistics(self.db)['setups'],2)
    def test_config_hash_collision_is_rejected(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z]);wrong=copy.deepcopy(z)
        wrong['config_hash']='invalidconfig'
        wrong['candidates'][0]['config_hash']='invalidconfig'
        with self.assertRaisesRegex(ValueError,'RULE_VERSION_CONFIG_HASH_COLLISION'):persist_batch(self.db,[wrong])
    def test_relational_constraints_and_event_payload_json(self):
        z=synthetic_one([Decimal('1.5')]);persist_batch(self.db,[z])
        e=self.db.execute('SELECT * FROM reversal_setup_event LIMIT 1').fetchone()
        self.assertIn('context_structure_ids',json.loads(e['event_payload']))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:self.db.execute("INSERT INTO reversal_setup_event(event_id,setup_id,event_type,event_time,available_at,reason_code,event_payload,rule_version,config_hash,created_at) VALUES ('bad','missing','CREATED','t','t','r','{}','v','hash','now')")

class Phase4RealSnapshot(unittest.TestCase):
    def test_real_four_candidates_and_two_long_signals(self):
        z=[real_one(t) for t in TICKERS]
        self.assertEqual(sum(len(x['candidates']) for x in z),4)
        self.assertEqual([s['status'] for x in z for s in x['candidates']],['INVALIDATED','EXPIRED','FOUND','FOUND'])
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'real.sqlite')
            try:
                first=persist_batch(conn,z);second=persist_batch(conn,z)
                self.assertEqual((first['inserted'],first['events_inserted'],second['inserted'],second['events_inserted']), (4,8,0,0))
                self.assertEqual(statistics(conn)['by_status'],dict(INVALIDATED=1,EXPIRED=1,FOUND=2))
                signals=export_long_setups(conn);self.assertEqual(len(signals),2)
                self.assertEqual([s['ticker'] for s in signals],['FPT','SSI'])
                self.assertEqual([s['window_crosses_session'] for s in signals],[False,True])
                self.assertTrue(all(s['calendar_source_verification']=='UNVERIFIED' for s in signals))
                self.assertTrue(all(s['context_age_bars'] is not None for s in signals))
                self.assertEqual(Decimal(signals[-1]['body_ratio']),Decimal('1.0'))
                self.assertEqual(signals[-1]['signal_available_at'],'2026-10-16T09:30:00+07:00')
            finally:conn.close()
    def test_real_HPG_invalidation_equal_time_no_long(self):
        hpg=real_one('HPG')['candidates'][0]
        self.assertEqual(hpg['status'],'INVALIDATED')
        self.assertEqual(hpg['reason_code'],'CONTEXT_STRUCTURE_BROKEN')
        self.assertEqual(hpg['resolved_at'],'2026-10-05T09:30:00+07:00')
        self.assertIsNone(hpg['reversal_candle_time'])
    def test_holiday_weekend_window_crosses_to_next_verified_trading_date(self):
        # 2026-08-31, 09-01, 09-02 exchange holidays; Fri Aug28 -> Thu Sep03.
        from reversal_setup_detector.calendar_phase3 import HOLIDAYS_IN_SNAPSHOT
        self.assertTrue({'2026-08-31','2026-09-01','2026-09-02'}.issubset(HOLIDAYS_IN_SNAPSHOT))
        r=ApprovedRules();slots=[];bars=[]
        def put(date,hm,op,cl,session):
            from datetime import datetime,timedelta
            start=datetime.fromisoformat(f'{date}T{hm}:00+07:00')
            slots.append(dict(open_at=start,close_at=start+timedelta(minutes=15),session_id=session))
            bars.append(make_bar(hm,op,cl,date=date))
        for hm,op,cl in [('14:00',120,110),('14:15',110,109),('14:45',110,100)]:
            put('2026-08-28',hm,op,cl,'2026-08-28:PM')
        for hm,op,cl in [('09:15',100,100),('09:30',100,100),('09:45',100,100),('10:00',100,100),('10:15',100,110)]:
            put('2026-09-03',hm,op,cl,'2026-09-03:AM')
        cal=Calendar(slots,r,calendar_id='SYNTHETIC_EXCHANGE_HOLIDAY',verified=False,
             coverage_start='2026-08-28T13:00:00+07:00',coverage_end='2026-09-03T11:30:00+07:00')
        provider=ContextProvider(fixture([dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN')]),rules=r)
        z=scan_lifecycle(bars,r,cal,provider,as_of=cal.end,ticker='TEST',timeframe='15m',source_version='fixture-v1')
        self.assertEqual(len(z['candidates']),1)
        s=z['candidates'][0]
        self.assertEqual(s['status'],'FOUND');self.assertEqual(s['bars_checked'],5)
        self.assertTrue(s['window_crosses_session'])
        self.assertEqual(s['reversal_candle_time'],'2026-09-03T10:15:00+07:00')
        self.assertEqual(z['metrics']['data_gaps'],0)
        self.assertFalse(z['calendar_verified'])
    def test_holiday_next_trading_day_missing_bar_invalidates_not_skipped(self):
        from datetime import datetime,timedelta
        r=ApprovedRules();slots=[];bars=[]
        for date,times,session in [('2026-08-28',['14:00','14:15','14:45'],'PM'),
                                  ('2026-09-03',['09:15','09:30'],'AM')]:
            for hm in times:
                start=datetime.fromisoformat(f'{date}T{hm}:00+07:00')
                slots.append(dict(open_at=start,close_at=start+timedelta(minutes=15),session_id=f'{date}:{session}'))
                if date=='2026-09-03' and hm=='09:15':continue
                idx=times.index(hm)
                op,cl=[(120,110),(110,109),(110,100)][idx] if date=='2026-08-28' else (100,110)
                bars.append(make_bar(hm,op,cl,date=date))
        cal=Calendar(slots,r,calendar_id='SYNTHETIC_MISSING_AFTER_HOLIDAY',verified=True,
             coverage_start='2026-08-28T13:00:00+07:00',coverage_end='2026-09-03T11:30:00+07:00')
        provider=ContextProvider(fixture([dict(id='A',hour=10,direction='DOWN'),dict(id='B',hour=11,direction='DOWN')]),rules=r)
        z=scan_lifecycle(bars,r,cal,provider,as_of=cal.end,ticker='TEST',timeframe='15m',source_version='fixture-v1')
        s=z['candidates'][0]
        self.assertEqual(s['status'],'INVALIDATED')
        self.assertEqual(s['reason_code'],'DATA_GAP_IN_CANDLE_SEQUENCE')
        self.assertGreaterEqual(z['metrics']['data_gaps'],1)
    def test_approved_rule_and_unverified_calendar(self):
        r=ApprovedRules();self.assertEqual(r.version,'L3_REVERSAL_V1')
        self.assertTrue(r.get('allow_cross_session_sequences'))
        self.assertEqual(r.get('decision_status')['L3-D04'],'APPROVED')
        self.assertEqual(r.get('decision_status')['L3-D03'],'CONDITIONALLY_APPROVED')
        self.assertFalse(empirical_calendar(r,'HPG').verified)

if __name__=='__main__':unittest.main()
