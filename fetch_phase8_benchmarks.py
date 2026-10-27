"""Optional Vnstock v5 adapter; stage CSV first, never invent missing history."""
import argparse,json
from pathlib import Path
import pandas as pd
from src.phase8.data import read,ingest,validate

def fetch(db,start='2010-01-01',apply=False):
    try:from vnstock import Market
    except ImportError as exc:return {'status':'PROVIDER_UNAVAILABLE','rows':0,'reason':str(exc),'action':'Cài vnstock v5 theo hướng dẫn chính thức; hoặc nhập CSV benchmarks từ nguồn được cấp quyền.'}
    old=read(db,'benchmarks');today=pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').strftime('%Y-%m-%d');end=(pd.Timestamp(today)-pd.Timedelta(days=1)).strftime('%Y-%m-%d');results=[];dest=Path('data/inbox8');dest.mkdir(parents=True,exist_ok=True)
    for symbol in ['VNINDEX','VN30','HNXINDEX']:
        prior=old.loc[old.symbol==symbol];begin=(pd.Timestamp(prior.date.max())+pd.Timedelta(days=1)).strftime('%Y-%m-%d') if not prior.empty else start
        if begin>end:results.append({'symbol':symbol,'status':'UP_TO_DATE','rows':0});continue
        try:
            f=Market().index(symbol).ohlcv(start=begin,end=end,interval='1D',source='kbs',floating=None)
            if f.empty:raise ValueError('Provider trả rỗng')
            out=pd.DataFrame({'symbol':symbol,'date':pd.to_datetime(f.time).dt.strftime('%Y-%m-%d'),'close':f.close,'source':'vnstock5/'+str(f.attrs.get('source','kbs')),'known_at':today});out=validate('benchmarks',out);target=dest/(symbol+'.csv');out.to_csv(target,index=False)
            result={'symbol':symbol,'status':'STAGED','rows':len(out),'first':out.date.min(),'last':out.date.max(),'requested_start':begin,'coverage_warning':'Provider có thể giới hạn lịch sử; known_at là ngày tải, không chứng nhận vintage lịch sử','csv':str(target)}
            if apply:result['import']=ingest(db,'benchmarks',out)
            results.append(result)
        except Exception as exc:results.append({'symbol':symbol,'status':'FETCH_FAILED','rows':0,'reason':str(exc)})
    return {'status':'CHECK_EACH_SYMBOL','items':results,'rows':sum(r['rows'] for r in results)}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',default='data/state/qta_phase3_test.db');p.add_argument('--start',default='2010-01-01');p.add_argument('--apply',action='store_true');a=p.parse_args();print(json.dumps(fetch(a.db,a.start,a.apply),ensure_ascii=False,indent=2))
