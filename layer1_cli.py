"""Run independent Layer 1; does not invoke Layer 2 or touch a database."""
import argparse,json,logging
from pathlib import Path
import pandas as pd
from swing_detector import SwingDetectorConfig,detect_result
from swing_detector.io import export_result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ticker',required=True);p.add_argument('--csv',required=True);p.add_argument('--output',default='data/layer1_swings.csv')
    p.add_argument('--k',type=float,default=2.);p.add_argument('--left',type=int,default=3);p.add_argument('--right',type=int,default=3)
    p.add_argument('--min-bars',type=int,default=0);p.add_argument('--as-of');p.add_argument('--timestamp-label',choices=['open','close'],default='open')
    p.add_argument('--calendar-csv',help='CSV with Datetime column listing expected bar labels')
    a=p.parse_args();logging.basicConfig(level=logging.INFO)
    cfg=SwingDetectorConfig(ticker=a.ticker,reversal_atr_mult=a.k,pivot_left=a.left,pivot_right=a.right,min_bars_between_swings=a.min_bars,timestamp_label=a.timestamp_label)
    expected=pd.read_csv(a.calendar_csv).Datetime if a.calendar_csv else None
    r=detect_result(pd.read_csv(a.csv),cfg,as_of=a.as_of,expected_timestamps=expected);export_result(r,a.output)
    Path(a.output+'.audit.json').write_text(json.dumps({'diagnostics':r.diagnostics,'events':r.events},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':a.output,'swings':len(r.swings),'last_available':str(r.candles.available_time.iloc[-1]) if len(r.candles) else None},ensure_ascii=False))
if __name__=='__main__':main()
