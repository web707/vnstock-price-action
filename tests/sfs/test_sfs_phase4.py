import copy,json,tempfile,unittest
import pandas as pd
from structure_builder_sfs.phase4 import MajorContext,ContextRules,canonical,digest
from structure_builder_sfs.phase4_store import ContextStore
from structure_builder_sfs.phase3 import STRUCTURE_COLUMNS

def T(hour):return pd.Timestamp('2026-01-05',tz='Asia/Ho_Chi_Minh')+pd.Timedelta(hours=hour)
def fixture(specs=None):
    specs=specs or [dict(id='S1',hour=10,direction='UP'),dict(id='S2',hour=11,direction='DOWN'),dict(id='S3',hour=12,direction='UP',broken=13)]
    rules=ContextRules();events=[]
    for spec in specs:
        c=T(spec['hour']);r=dict.fromkeys(STRUCTURE_COLUMNS)
        r.update(structure_id=spec['id'],ticker=spec.get('ticker','TEST'),timeframe='15m',source_version=spec.get('source','fixture-v1'),rule_version=rules.get('upstream_rule_version'),config_hash=rules.get('upstream_config_hash'),structure_direction=spec.get('direction','UP'),start_swing_id=spec['id']+'a',end_swing_id=spec['id']+'d',start_time=c-pd.Timedelta(hours=3),end_time=c-pd.Timedelta(hours=1),classification='UNCLASSIFIED',geometry_qualified=False,protected_level=100)
        statuses=[('FORMING',c-pd.Timedelta(hours=1))]
        statuses.append(('UNCLEAR' if spec.get('rejected') else 'CONFIRMED',c))
        if 'broken' in spec:statuses.append(('BROKEN',T(spec['broken'])))
        old=None
        for seq,(status,at) in enumerate(statuses,1):
            r.update(status=status,available_at=at,event_time=at)
            if status in ('CONFIRMED','BROKEN'):
                r.update(confirmed_at=c,end_time=c-pd.Timedelta(minutes=15),atr_reference=spec.get('atr',10),amplitude_atr=spec.get('ratio',4.),geometry_qualified=True)
            if status=='BROKEN':r['invalidated_at']=at
            e=dict(event_id=digest([spec['id'],seq]),structure_id=r['structure_id'],old_status=old,new_status=status,event_type=status,event_time=at,available_at=at,reason_code='FIXTURE',source_version=r['source_version'],rule_version=r['rule_version'],config_hash=r['config_hash'],event_sequence=seq,payload_json=canonical({'after':r}))
            events.append(e);old=status
    return pd.DataFrame(events)
STREAM=dict(ticker='TEST',timeframe='15m',source_version='fixture-v1')
def query(e,at=14,mode='EVER_CONFIRMED'):return e.last_two(T(at),mode=mode,**STREAM)
def ids(context):return [r['structure_id'] for r in context['structures']]

class Phase4Tests(unittest.TestCase):
    def setUp(self):self.events=fixture();self.engine=MajorContext(self.events)
    def test_TC12_latest_two_without_skipping_broken(self):
        self.assertEqual(ids(query(self.engine,12)),['S2','S3'])
        c=query(self.engine,14);self.assertEqual(ids(c),['S2','S3']);self.assertEqual(c['structures'][-1]['status'],'BROKEN')
    def test_TC13_insufficient_one_and_zero(self):
        for hour,n in [(8,0),(10,1)]:
            c=query(self.engine,hour);self.assertEqual(c['context_status'],'INSUFFICIENT_STRUCTURE');self.assertEqual(len(c['structures']),n);self.assertIsNone(c['older_structure_id'])
        self.assertEqual(query(self.engine,10)['latest_structure_id'],'S1')
    def test_TC14_preserve_DOWN_in_chain_and_context(self):
        snap=self.engine.snapshot(T(14),**STREAM);self.assertEqual([r['structure_direction'] for r in snap['major_sequence']],['UP','DOWN','UP'])
        self.assertEqual(query(self.engine)['structures'][0]['structure_direction'],'DOWN')
    def test_TC18_long_null_reason_in_every_mode_and_state(self):
        for mode in ('EVER_CONFIRMED','ACTIVE'):
            for hour in (8,10,12,14):
                c=query(self.engine,hour,mode);self.assertIsNone(c['is_long_candidate']);self.assertEqual(c['reason_code'],'LONG_CONTEXT_NOT_EVALUATED')
    def test_modes_are_distinct(self):
        self.assertEqual(ids(query(self.engine,14,'ACTIVE')),['S1','S2']);self.assertEqual(ids(query(self.engine,14)),['S2','S3'])
        self.assertNotEqual(query(self.engine,14,'ACTIVE')['context_id'],query(self.engine,14)['context_id'])
    def test_no_default_mode(self):
        with self.assertRaises(TypeError):self.engine.last_two(T(14),**STREAM)
        for mode in (None,'BOTH','confirmed'):
            with self.assertRaises(ValueError):self.engine.last_two(T(14),mode=mode,**STREAM)
    def test_break_boundary_inclusive(self):
        self.assertEqual(ids(query(self.engine,12.99,'ACTIVE')),['S2','S3']);self.assertEqual(ids(query(self.engine,13,'ACTIVE')),['S1','S2'])
    def test_confirmation_boundary_inclusive(self):
        self.assertEqual(ids(query(self.engine,11.99)),['S1','S2']);self.assertEqual(ids(query(self.engine,12)),['S2','S3'])
    def test_chain_numbers_and_previous_ids(self):
        chain=self.engine.snapshot(T(14),**STREAM)['major_sequence'];self.assertEqual([r['structure_sequence_no'] for r in chain],[1,2,3]);self.assertEqual([r['previous_major_structure_id'] for r in chain],[None,'S1','S2'])
    def test_active_does_not_renumber_history(self):
        e=MajorContext(fixture([dict(id='S1',hour=10,broken=12),dict(id='S2',hour=11),dict(id='S3',hour=12)]))
        c=query(e,14,'ACTIVE');self.assertEqual([r['structure_sequence_no'] for r in c['structures']],[2,3]);self.assertEqual(c['structures'][0]['previous_major_structure_id'],'S1')
    def test_D04_equal_boundary_major_and_below_internal(self):
        e=MajorContext(fixture([dict(id='S1',hour=10,ratio=3.),dict(id='S2',hour=11,ratio=2.999999),dict(id='S3',hour=12,ratio=4.)]))
        snap=e.snapshot(T(14),**STREAM);labels={r['structure_id']:r['classification'] for r in snap['classified_structures']};self.assertEqual(labels,{'S1':'MAJOR','S2':'INTERNAL','S3':'MAJOR'});self.assertEqual(ids(query(e)),['S1','S3'])
    def test_missing_ATR_unclassified(self):
        e=MajorContext(fixture([dict(id='S1',hour=10,atr=None,ratio=None)]));snap=e.snapshot(T(14),**STREAM);self.assertEqual(snap['major_sequence'],[]);self.assertEqual(snap['classified_structures'][0]['classification_reason_code'],'ATR_MISSING_OR_INVALID')
    def test_forming_and_rejected_excluded(self):
        e=MajorContext(fixture([dict(id='S1',hour=10,rejected=True),dict(id='S2',hour=16)]));snap=e.snapshot(T(15),**STREAM);self.assertEqual(snap['major_sequence'],[]);self.assertTrue(all(r['classification']=='UNCLASSIFIED' for r in snap['classified_structures']))
    def test_no_lookahead_prefix(self):
        for hour in (8,9,10,11,12,12.5,13,14):
            prefix=MajorContext(self.events[self.events.available_at<=T(hour)])
            for mode in ('EVER_CONFIRMED','ACTIVE'):self.assertEqual(canonical(query(prefix,hour,mode)),canonical(query(self.engine,hour,mode)))
    def test_versions_separate_context_ids(self):
        config=ContextRules().as_dict();config['rule_version']='phase4-v2';e=MajorContext(self.events,ContextRules(config));self.assertNotEqual(query(e)['context_id'],query(self.engine)['context_id']);self.assertEqual(ids(query(e)),ids(query(self.engine)))
    def test_upstream_version_mismatch_rejected(self):
        events=self.events.copy();events.loc[0,'rule_version']='wrong'
        with self.assertRaisesRegex(ValueError,'UPSTREAM_VERSION'):query(MajorContext(events))
    def test_event_history_gap_rejected(self):
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_EVENT_HISTORY'):query(MajorContext(self.events.iloc[1:]))
    def test_conflicting_duplicate_rejected(self):
        duplicate=self.events.iloc[:1].copy();duplicate['reason_code']='different'
        with self.assertRaisesRegex(ValueError,'CONFLICTING_EVENT'):query(MajorContext(pd.concat([self.events,duplicate])))
    def test_identical_duplicate_idempotent(self):
        self.assertEqual(canonical(query(MajorContext(pd.concat([self.events,self.events.iloc[:1]])))),canonical(query(self.engine)))
    def test_input_order_independent(self):self.assertEqual(canonical(query(MajorContext(self.events.iloc[::-1]))),canonical(query(self.engine)))
    def test_source_and_ticker_isolated(self):
        extra=fixture([dict(id='OTHER',hour=13,source='other'),dict(id='OTHER2',hour=13,ticker='OTHER')]);e=MajorContext(pd.concat([self.events,extra]));self.assertEqual(ids(query(e)),['S2','S3'])
    def test_ties_deterministic(self):
        events=fixture([dict(id='B',hour=10),dict(id='A',hour=10),dict(id='C',hour=10)])
        self.assertEqual(ids(query(MajorContext(events))),['B','C'])
    def test_timezone_equivalence(self):self.assertEqual(canonical(self.engine.last_two(T(14).tz_convert('UTC'),mode='ACTIVE',**STREAM)),canonical(query(self.engine,14,'ACTIVE')))
    def test_no_mutation_of_input_or_results(self):
        before=self.events.copy(deep=True);c=query(self.engine);c['structures'][0]['classification']='WRONG';self.assertEqual(query(self.engine)['structures'][0]['classification'],'MAJOR');pd.testing.assert_frame_equal(before,self.events)
    def test_config_immutable(self):
        c=ContextRules().as_dict();p=ContextRules(c);h=p.config_hash;c['amplitude_threshold_atr']=99;p.get('query_modes').clear();self.assertEqual(p.config_hash,h)
    def test_default_and_long_enable_rejected(self):
        for key,value in [('default_query_mode','ACTIVE'),('long_enabled',True),('directions',['UP'])]:
            c=ContextRules().as_dict();c[key]=value
            with self.assertRaises(ValueError):ContextRules(c)
    def test_store_idempotent_and_both_modes_SQL_NULL(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=ContextStore(tmp+'/c');snap=self.engine.snapshot(T(14),**STREAM);contexts=[query(self.engine,14,m) for m in ('EVER_CONFIRMED','ACTIVE')]
            st.save(snap,contexts);st.save(snap,contexts)
            self.assertEqual(st.db.execute('SELECT count(*) FROM major_structure_sequence').fetchone()[0],3)
            self.assertEqual(st.db.execute('SELECT count(*) FROM structure_context_snapshot').fetchone()[0],2)
            self.assertEqual(st.db.execute('SELECT count(*) FROM structure_context_snapshot WHERE is_long_candidate IS NULL').fetchone()[0],2);st.close()
    def test_store_rule_version_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=ContextStore(tmp+'/c');snap=self.engine.snapshot(T(14),**STREAM);st.save(snap,[])
            c=ContextRules().as_dict();c['amplitude_threshold_atr']=2.5;e=MajorContext(self.events,ContextRules(c))
            with self.assertRaisesRegex(ValueError,'RULE_VERSION_CONFIG_CONFLICT'):st.save(e.snapshot(T(14),**STREAM),[])
            st.close()
    def test_store_versions_coexist_and_past_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=ContextStore(tmp+'/c');s=self.engine.snapshot(T(14),**STREAM);st.save(s,[query(self.engine)]);st.save(self.engine.snapshot(T(12),**STREAM),[query(self.engine,12)])
            c=ContextRules().as_dict();c['rule_version']='v2';e=MajorContext(self.events,ContextRules(c));st.save(e.snapshot(T(14),**STREAM),[query(e)])
            self.assertEqual(st.db.execute('SELECT count(*) FROM phase4_snapshot').fetchone()[0],3);self.assertEqual(st.db.execute('SELECT count(*) FROM phase4_rule_version').fetchone()[0],2);st.close()
    def test_store_snapshot_conflict_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=ContextStore(tmp+'/c');s=self.engine.snapshot(T(14),**STREAM);st.save(s,[]);s['classified_structures'][0]['classification']='INTERNAL'
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_SNAPSHOT_CONFLICT'):st.save(s,[])
            self.assertEqual(st.db.execute('SELECT count(*) FROM major_structure_sequence').fetchone()[0],3);st.close()
    def test_store_context_conflict_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=ContextStore(tmp+'/c');s=self.engine.snapshot(T(14),**STREAM);c=query(self.engine);st.save(s,[c]);c['older_structure_id']='wrong'
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_CONTEXT_CONFLICT'):st.save(s,[c])
            self.assertEqual(st.db.execute('SELECT count(*) FROM structure_context_snapshot').fetchone()[0],1);st.close()
