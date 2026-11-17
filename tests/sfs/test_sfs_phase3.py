import copy,json,tempfile,unittest
import pandas as pd
from structure_builder_sfs.phase3 import StructureEngine,build_structures,semantic
from structure_builder_sfs.phase3_rules import RuleProvider
from structure_builder_sfs.phase3_store import StructureStore

TZ='Asia/Ho_Chi_Minh'
def T(h):return pd.Timestamp('2026-01-05 '+h,tz=TZ)
def fixture(down=False):
    types=['HIGH','LOW','HIGH','LOW'] if down else ['LOW','HIGH','LOW','HIGH']
    prices=[140,110,130,100] if down else [100,130,110,140]
    swings=pd.DataFrame([dict(swing_id=i+1,ticker='TEST',timeframe='15m',swing_type=types[i],extreme_price=prices[i],extreme_time=T('%02d:00'%(9+2*i)),confirmed_at=T('%02d:00'%(10+2*i)),atr_at_extreme=20,source_version='fixture-v1') for i in range(4)])
    bars=pd.DataFrame([dict(Datetime=t,Open=120,High=125,Low=115,Close=120,Volume=10) for t in pd.date_range(T('09:00'),T('18:00'),freq='15min')])
    return swings,bars

def price(b,at,p):
    b=b.copy();m=b.Datetime>=T(at);b.loc[m,['Open','Close']]=p;b.loc[m,'High']=max(p,125);b.loc[m,'Low']=min(p,115);return b

def run(s,b,at='18:15',p=None):return build_structures(s,b,as_of=T(at),provider=p)
def first(r):return r['market_structure'].iloc[0]
def semantic_rows(r):return [semantic(x) for x in r['market_structure'].to_dict('records')]

class Phase3Tests(unittest.TestCase):
    def setUp(self):self.s,self.b=fixture()
    def test_TC10_confirmation_and_available_at(self):
        r=run(self.s,self.b,'16:00');x=first(r)
        self.assertEqual(x.status,'CONFIRMED');self.assertEqual(x.confirmed_at,T('16:00'));self.assertEqual(x.available_at,T('16:00'))
        self.assertEqual(x.protected_level,110);self.assertEqual(x.classification,'UNCLASSIFIED')
    def test_TC11_break_close_fields(self):
        r=run(self.s,price(self.b,'16:00',109));x=first(r)
        self.assertEqual(x.status,'BROKEN');self.assertEqual(x.invalidated_at,T('16:15'));self.assertEqual(x.break_candle_time,T('16:00'));self.assertEqual(x.break_price,109);self.assertEqual(x.reason_code,'STRUCTURE_BROKEN')
    def test_TC15_prefix_and_every_bar_replay(self):
        b=price(self.b,'16:00',109);full=StructureEngine(self.s,b);full.advance(T('18:15'));inc=StructureEngine(self.s,b)
        for t in b.Datetime+pd.Timedelta(minutes=15):
            got=inc.advance(t);expected=full.snapshot(t)
            self.assertEqual(got['market_structure_event'].to_dict('records'),expected['market_structure_event'].to_dict('records'))
            prefix=build_structures(self.s[self.s.confirmed_at<=t],b[b.Datetime+pd.Timedelta(minutes=15)<=t],as_of=t)
            self.assertEqual(semantic_rows(prefix),semantic_rows(expected))
    def test_TC17_versioned_ids_and_store(self):
        c=RuleProvider().as_dict();c['rule_version']='alternate-v2';a=run(self.s,self.b);b=run(self.s,self.b,p=RuleProvider(c))
        self.assertNotEqual(first(a).structure_id,first(b).structure_id)
        with tempfile.TemporaryDirectory() as tmp:
            st=StructureStore(tmp+'/x.sqlite');st.save(a);st.save(b)
            self.assertEqual(st.db.execute('SELECT count(*) FROM market_structure').fetchone()[0],2)
            self.assertEqual(st.db.execute('SELECT count(*) FROM structure_rule_version').fetchone()[0],2);st.close()
    def test_forming_after_three_swings(self):self.assertEqual(first(run(self.s,self.b,'14:00')).status,'FORMING')
    def test_no_candidate_with_two_swings(self):self.assertTrue(run(self.s,self.b,'13:59')['market_structure'].empty)
    def test_down_symmetric_break(self):
        s,b=fixture(True);x=first(run(s,price(b,'16:00',131)));self.assertEqual(x.status,'BROKEN');self.assertEqual(x.protected_level,130)
    def test_prebroken_retained_never_confirmed_both_directions(self):
        for down,p in [(False,109),(True,131)]:
            s,b=fixture(down);r=run(s,price(b,'15:45',p));x=first(r)
            self.assertEqual(x.status,'UNCLEAR');self.assertEqual(x.reason_code,'PROTECTED_LEVEL_VIOLATED_AT_AVAILABILITY');self.assertIsNone(x.confirmed_at);self.assertIsNone(x.invalidated_at)
            self.assertNotIn('CONFIRMED',list(r['market_structure_event'].new_status))
    def test_prebroken_does_not_resurrect(self):
        b=price(self.b,'15:45',109);b=price(b,'16:00',120)
        self.assertEqual(first(run(self.s,b)).status,'UNCLEAR')
    def test_full_geometry_failure_retained(self):
        self.s.loc[3,'extreme_price']=125;r=run(self.s,self.b)
        self.assertEqual(first(r).status,'UNCLEAR');self.assertEqual(first(r).reason_code,'STRUCTURE_RULE_NOT_MET')
    def test_partial_geometry_failure(self):
        self.s.loc[2,'extreme_price']=90;self.assertTrue(run(self.s,self.b,'14:00')['market_structure'].empty)
    def test_equal_high_not_strict(self):
        self.s.loc[3,'extreme_price']=131;self.assertFalse(first(run(self.s,self.b)).geometry_qualified)
    def test_D04_amplitude_below_3ATR_not_gate(self):
        x=first(run(self.s,self.b));self.assertEqual(x.amplitude_atr,2);self.assertFalse(x.amplitude_filter_passed);self.assertEqual(x.status,'CONFIRMED')
    def test_missing_ATR_does_not_block_geometry(self):
        self.s.loc[0,'atr_at_extreme']=None;x=first(run(self.s,self.b));self.assertIsNone(x.amplitude_atr);self.assertEqual(x.status,'CONFIRMED')
    def test_touch_not_break(self):self.assertEqual(first(run(self.s,price(self.b,'16:00',110))).status,'CONFIRMED')
    def test_wick_not_break(self):
        self.b.loc[self.b.Datetime>=T('16:00'),'Low']=90;self.assertEqual(first(run(self.s,self.b)).status,'CONFIRMED')
    def test_break_only_when_bar_closed(self):self.assertEqual(first(run(self.s,price(self.b,'16:00',109),'16:14')).status,'CONFIRMED')
    def test_break_once(self):self.assertEqual(sum(run(self.s,price(self.b,'16:00',109))['market_structure_event'].new_status=='BROKEN'),1)
    def test_break_rule_unconfigured_fail_closed(self):
        c=RuleProvider().as_dict();c['break_rule_status']='UNCONFIGURED';self.assertEqual(first(run(self.s,self.b,p=RuleProvider(c))).reason_code,'BREAK_RULE_NOT_CONFIGURED')
    def test_break_keys_missing_fail_closed(self):
        c=RuleProvider().as_dict();del c['break_basis'];del c['break_rule_status'];del c['directions']['UP']['break_operator']
        self.assertEqual(first(run(self.s,self.b,p=RuleProvider(c))).reason_code,'BREAK_RULE_NOT_CONFIGURED')
    def test_phase5_variants_disabled(self):
        for name in ('D06-C','D07-C'):
            c=RuleProvider().as_dict();c['phase5_variants'][name]['enabled']=True
            with self.assertRaises(ValueError):RuleProvider(c)
    def test_rule_config_deep_copied(self):
        c=RuleProvider().as_dict();p=RuleProvider(c);h=p.config_hash;c['atr_multiplier']=99;p.get('directions')['UP']['pattern']=[];self.assertEqual(p.config_hash,h)
    def test_event_history_immutable(self):
        e=StructureEngine(self.s,price(self.b,'16:00',109));r=e.advance(T('16:00'));before=copy.deepcopy(r['market_structure_event'].to_dict('records'));e.advance(T('18:15'))
        self.assertEqual(e.snapshot(T('16:00'))['market_structure_event'].to_dict('records'),before)
    def test_returned_payload_isolated(self):
        e=StructureEngine(self.s,self.b);r=e.advance(T('16:00'));r['market_structure_event'].loc[0,'payload_json']='corrupted';self.assertNotEqual(e.snapshot(T('16:00'))['market_structure_event'].iloc[0].payload_json,'corrupted')
    def test_store_idempotent_and_no_rewind(self):
        e=StructureEngine(self.s,price(self.b,'16:00',109));r=e.advance(T('18:15'))
        with tempfile.TemporaryDirectory() as tmp:
            st=StructureStore(tmp+'/x');st.save(r);st.save(r);st.save(e.snapshot(T('16:00')))
            self.assertEqual(st.db.execute('SELECT count(*) FROM market_structure_event').fetchone()[0],3)
            self.assertEqual(st.db.execute('SELECT status FROM market_structure').fetchone()[0],'BROKEN')
            self.assertEqual(st.historical_rows(T('16:00'),RuleProvider().version)[0]['status'],'CONFIRMED');st.close()
    def test_same_version_config_conflict(self):
        c=RuleProvider().as_dict();c['atr_multiplier']=9
        with tempfile.TemporaryDirectory() as tmp:
            st=StructureStore(tmp+'/x');st.save(run(self.s,self.b))
            with self.assertRaisesRegex(ValueError,'RULE_VERSION_CONFIG_CONFLICT'):st.save(run(self.s,self.b,p=RuleProvider(c)))
            st.close()
    def test_event_source_conflict_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            st=StructureStore(tmp+'/x');a=run(self.s,self.b);st.save(a);a['market_structure_event'].loc[0,'reason_code']='wrong'
            with self.assertRaisesRegex(ValueError,'HISTORICAL_EVENT_CONFLICT'):st.save(a)
            self.assertEqual(st.db.execute('SELECT count(*) FROM market_structure_event').fetchone()[0],2);st.close()
    def test_no_major_or_context(self):
        r=run(self.s,self.b);self.assertEqual(set(r['market_structure'].classification),{'UNCLASSIFIED'});self.assertTrue(r['market_structure'].previous_major_structure_id.isna().all());self.assertNotIn('structure_context_snapshot',r)
    def test_duplicate_input_deduplicated(self):
        a=run(self.s,self.b);b=run(pd.concat([self.s,self.s.iloc[:1]],ignore_index=True),pd.concat([self.b,self.b.iloc[:1]],ignore_index=True));self.assertEqual(semantic_rows(a),semantic_rows(b))
    def test_missing_candles_fail_closed(self):self.assertTrue(run(self.s,self.b.iloc[:0])['market_structure'].empty)
    def test_bad_later_swing_does_not_erase_history(self):
        e=StructureEngine(self.s,self.b);expected=e.advance(T('16:00'))
        extra=self.s.iloc[-1:].copy();extra['swing_id']=5;extra['extreme_time']=T('16:30');extra['confirmed_at']=T('17:30');s=pd.concat([self.s,extra],ignore_index=True)
        actual=run(s,self.b);self.assertEqual(semantic_rows(expected),semantic_rows(actual));self.assertIn('INVALID_SWING_SEQUENCE',list(actual['audit'].reason_code))
    def test_inputs_unchanged(self):
        s=self.s.copy(deep=True);b=self.b.copy(deep=True);run(self.s,self.b);pd.testing.assert_frame_equal(s,self.s);pd.testing.assert_frame_equal(b,self.b)
