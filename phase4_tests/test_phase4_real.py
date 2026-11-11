import unittest
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase4 import MajorContext,canonical
ROOT=Path(__file__).resolve().parents[1]
END='2026-10-28 23:59:59+07:00'
class RealContextTests(unittest.TestCase):
    def check_ticker(self,ticker,expected_major,expected_internal):
        folder=ROOT/'reports/layer2_phase3'/ticker
        events=pd.read_csv(folder/'market_structure_event.csv');original=pd.read_csv(folder/'market_structure.csv')
        stream=dict(ticker=ticker,timeframe='15m',source_version=original.source_version.iloc[0]);engine=MajorContext(events)
        final=engine.snapshot(END,**stream);rows=final['classified_structures'];major=final['major_sequence']
        self.assertEqual(len(major),expected_major);self.assertEqual(sum(r['classification']=='INTERNAL' for r in rows),expected_internal)
        self.assertEqual({r['structure_id'] for r in major if r['structure_direction']=='DOWN'},set(original.loc[(original.structure_direction=='DOWN')&original.confirmed_at.notna()&(original.amplitude_atr>=3),'structure_id']))
        self.assertEqual({r['structure_id'] for r in major if r['structure_direction']=='UP'},set(original.loc[(original.structure_direction=='UP')&original.confirmed_at.notna()&(original.amplitude_atr>=3),'structure_id']))
        availability=pd.to_datetime(events.available_at)
        cutoffs=sorted(set(availability))
        # Each event boundary and one microsecond before: no future state leakage.
        for boundary in cutoffs:
            for at in (boundary-pd.Timedelta(microseconds=1),boundary):
                prefix=MajorContext(events[availability<=at]);a=prefix.snapshot(at,**stream);b=engine.snapshot(at,**stream)
                self.assertEqual(canonical(a),canonical(b))
                for mode in ('EVER_CONFIRMED','ACTIVE'):
                    c=engine.context_from_snapshot(b,mode=mode)
                    self.assertEqual(canonical(prefix.context_from_snapshot(a,mode=mode)),canonical(c))
                    self.assertTrue(all(r['confirmed_at']<=at for r in c['structures']))
                    if mode=='ACTIVE':self.assertTrue(all(r['status']=='CONFIRMED' for r in c['structures']))
                    self.assertIsNone(c['is_long_candidate'])
        if ticker=='HPG':
            rejected=[r for r in rows if r['start_swing_id']=='35' and r['end_swing_id']=='38'];self.assertEqual(len(rejected),1);self.assertEqual(rejected[0]['classification'],'UNCLASSIFIED')
        if ticker=='VNM':
            internal=[r for r in rows if r['classification']=='INTERNAL'];self.assertEqual([(r['start_swing_id'],r['end_swing_id']) for r in internal],[('62','65')])
        print(f'PHASE4 {ticker}: MAJOR={expected_major} INTERNAL={expected_internal}; {2*len(cutoffs)} point-in-time cutoffs x 2 query modes PASS',flush=True)
    def test_HPG_point_in_time_both_modes(self):self.check_ticker('HPG',10,0)
    def test_FPT_point_in_time_both_modes(self):self.check_ticker('FPT',12,0)
    def test_VNM_point_in_time_both_modes(self):self.check_ticker('VNM',14,1)
    def test_VCB_point_in_time_both_modes(self):self.check_ticker('VCB',15,0)
    def test_SSI_point_in_time_both_modes(self):self.check_ticker('SSI',12,0)
