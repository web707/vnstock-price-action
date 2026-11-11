"""Fetch actual intraday data only; errors are recorded, never replaced by synthetic bars."""
from pathlib import Path
import json,hashlib,datetime
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
ROOT=Path(__file__).resolve().parents[1]/'reports/layer1/fetched'

def fetch(symbol):
    record={'symbol':symbol,'ticker':symbol+'.VN','period':'60d','interval':'15m','auto_adjust':False,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        df=yf.Ticker(symbol+'.VN').history(period='60d',interval='15m',auto_adjust=False,timeout=15,raise_errors=True)
        if df.empty:raise ValueError('Empty provider response')
        df=df.reset_index();df=df.rename(columns={df.columns[0]:'Datetime'})
        path=ROOT/(symbol+'.csv');df.to_csv(path,index=False)
        record.update(rows=len(df),first=str(df.Datetime.iloc[0]),last=str(df.Datetime.iloc[-1]),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception as exc:record['error']=str(exc)
    return record
if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(fetch,['HPG','FPT','VNM','VCB','SSI']))
    (ROOT/'sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records,indent=2))
