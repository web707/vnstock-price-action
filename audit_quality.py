"""Audit daily price database without modifying it. Stop writers before running."""
import argparse
from datetime import date
from src.data_quality import audit_database,save_report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    p.add_argument('--as-of',type=date.fromisoformat,default=None)
    p.add_argument('--output',default='data/reports/data_quality.json')
    args=p.parse_args()
    report=audit_database(args.db,args.as_of.isoformat() if args.as_of else None)
    save_report(report,args.output)
    print({k:report[k] for k in ['integrity_check','universe_count','symbols_with_prices','total_bars','status_counts']})
