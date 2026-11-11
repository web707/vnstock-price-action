"""Structural lifetimes; incomplete active lifetimes remain right-censored."""
import pandas as pd

def describe(result,bars,rules):
 rows=result['market_structure'];e=rules.get('experiment');opens=pd.to_datetime(bars.Datetime);closes=opens+pd.Timedelta(minutes=15);last=closes.max();details=[]
 for r in rows[rows.confirmed_at.notna()].to_dict('records'):
  start=pd.Timestamp(r['confirmed_at']);broken=pd.notna(r['invalidated_at']);end=pd.Timestamp(r['invalidated_at']) if broken else last
  follow=closes[(opens>=start)&(closes<=last)];observed=closes[(opens>=start)&(closes<=end)]
  label='UNCLASSIFIED' if pd.isna(r['amplitude_atr']) else 'MAJOR' if r['amplitude_atr']>=e['classification_atr'] else 'INTERNAL'
  details.append(dict(structure_id=r['structure_id'],ticker=r['ticker'],scenario=e['name'],start_swing_id=r['start_swing_id'],end_swing_id=r['end_swing_id'],direction=r['structure_direction'],confirmed_at=start,invalidated_at=end if broken else None,censored=not broken,completed_lifetime_hours=(end-start).total_seconds()/3600 if broken else None,observed_age_hours=(end-start).total_seconds()/3600,lifetime_observed_bars=len(observed),available_followup_bars=len(follow),complete_20bar_horizon=len(follow)>=20,broken_within_20bars=broken and len(observed)<=20,classification=label,cohort=start.strftime('%Y-%m')))
 d=pd.DataFrame(details);completed=d[~d.censored] if len(d) else d;complete=d[d.complete_20bar_horizon] if len(d) else d
 stat=lambda col,op:float(getattr(completed[col],op)()) if len(completed) else None
 summary=dict(ticker=rows.iloc[0].ticker if len(rows) else '',scenario=e['name'],candidate_windows=int(rows.geometry_qualified.sum()),history_records=len(rows),ever_confirmed=len(d),BROKEN=len(completed),broken_rate_pct=100*len(completed)/len(d) if len(d) else None,active_censored=len(d)-len(completed),rejected_at_birth=int(rows.rejected_at.notna().sum()),completed_mean_hours=stat('completed_lifetime_hours','mean'),completed_median_hours=stat('completed_lifetime_hours','median'),completed_mean_bars=stat('lifetime_observed_bars','mean'),completed_median_bars=stat('lifetime_observed_bars','median'),censored_median_age_hours=float(d[d.censored].observed_age_hours.median()) if len(d) and d.censored.any() else None,complete_20bar_n=len(complete),broken_20bar_n=int(complete.broken_within_20bars.sum()) if len(complete) else 0,broken_20bar_pct=float(100*complete.broken_within_20bars.mean()) if len(complete) else None,MAJOR=sum(r['classification']=='MAJOR' for r in details),INTERNAL=sum(r['classification']=='INTERNAL' for r in details),last_closed_bar=str(last),rule_version=rules.version,config_hash=rules.config_hash)
 return summary,d
