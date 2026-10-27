"""Import user-supplied reference data, validated before replacing a reference CSV."""
import argparse,re
import numpy as np
import pandas as pd
from src.phase7.data import refdir
SCHEMAS={'benchmark':['DATE','CLOSE','SOURCE'],'calendar':['DATE','SOURCE'],'limits':['DATE','SYMBOL','FLOOR','CEILING','SOURCE'],'sectors':['SYMBOL','SECTOR','VALID_FROM','VALID_TO','SOURCE'],'units':['SYMBOL','UNIT','BASIS','SOURCE']}

def validate(name,f):
    if name not in SCHEMAS or not set(SCHEMAS[name]).issubset(f) or f.empty:raise ValueError('Thiếu cột/dữ liệu: '+name)
    f=f.copy()
    if f.SOURCE.fillna('').astype(str).str.strip().eq('').any():raise ValueError('Thiếu SOURCE')
    for col in ['DATE','VALID_FROM']:
        if col in f:
            d=pd.to_datetime(f[col],errors='coerce')
            if d.isna().any():raise ValueError('Ngày không hợp lệ')
            f[col]=d.dt.strftime('%Y-%m-%d')
    if 'SYMBOL' in f and not f.SYMBOL.astype(str).str.fullmatch(r'[A-Z0-9^][A-Z0-9.^-]{0,19}').all():raise ValueError('Mã không hợp lệ')
    for col in ['CLOSE','OPEN','HIGH','LOW','FLOOR','CEILING','VOLUME']:
        if col in f:
            n=pd.to_numeric(f[col],errors='coerce')
            if (~np.isfinite(n)).any() or ((n<0) if col=='VOLUME' else (n<=0)).any():raise ValueError('Số không hợp lệ '+col)
    if name in ('benchmark','calendar') and f.DATE.duplicated().any():raise ValueError('Trùng ngày')
    if name=='benchmark' and {'OPEN','HIGH','LOW','VOLUME'}.issubset(f):
        if (f.HIGH<f[['OPEN','CLOSE','LOW']].max(axis=1)).any() or (f.LOW>f[['OPEN','CLOSE','HIGH']].min(axis=1)).any():raise ValueError('OHLC sai')
    if name=='limits' and ((f.FLOOR>=f.CEILING).any() or f.duplicated(['SYMBOL','DATE']).any()):raise ValueError('Giới hạn/trùng ngày mã')
    if name=='units' and (f.SYMBOL.duplicated().any() or not f.UNIT.eq('VND').all() or not f.BASIS.eq('RAW').all()):raise ValueError('Cần RAW/VND duy nhất từng mã')
    if name=='sectors':
        if f.SECTOR.fillna('').str.strip().eq('').any():raise ValueError('Thiếu ngành')
        end=pd.to_datetime(f.VALID_TO,errors='coerce');bad=f.VALID_TO.notna()&end.isna()
        if bad.any():raise ValueError('Ngày kết thúc sai')
        f['VALID_TO']=end.dt.strftime('%Y-%m-%d')
        for _,g in f.groupby('SYMBOL'):
            g=g.sort_values('VALID_FROM');starts=pd.to_datetime(g.VALID_FROM).to_numpy();ends=pd.to_datetime(g.VALID_TO).fillna(pd.Timestamp.max).to_numpy()
            if (ends<starts).any() or (len(g)>1 and (starts[1:]<=ends[:-1]).any()):raise ValueError('Khoảng ngành chồng lấn')
    return f
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('kind',choices=SCHEMAS);p.add_argument('csv');args=p.parse_args();f=validate(args.kind,pd.read_csv(args.csv));root=refdir();root.mkdir(parents=True,exist_ok=True);target=root/(args.kind+'.csv');temp=target.with_suffix('.tmp');f.to_csv(temp,index=False);temp.replace(target);print('Saved',target,len(f),'rows. SOURCE là khai báo của người nhập, chưa được QTA xác minh độc lập.')
