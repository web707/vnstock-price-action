"""Read-only daily data diagnostics. Passing checks is not source verification."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd

FIELDS=['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','VOLUME']

def assess(frame, as_of=None):
    today=date.fromisoformat(str(as_of)) if as_of else pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date()
    result={'bars':len(frame),'status':'NO_DATA','last_date':None,'invalid_ohlcv':0,'invalid_dates':0,
            'duplicate_dates':0,'future_dates':0,'zero_volume':0,'unverified_rows':0,'warning_rows':0,
            'adj_close_missing':0,'large_moves':0,'elapsed_weekdays':None,'sources':[],
            'quality_labels':{},'price_basis':'unknown','reasons':[]}
    if frame.empty:
        result['reasons']=['Không có dữ liệu giá'];return result
    values=frame.reindex(columns=FIELDS).apply(pd.to_numeric,errors='coerce')
    o,h,l,c,v=(values[x] for x in FIELDS)
    bad=(~np.isfinite(values.to_numpy(dtype=float))).any(axis=1)|(o<=0)|(h<=0)|(l<=0)|(c<=0)|(v<0)|(v%1!=0)|(h<values.iloc[:,:4].max(axis=1))|(l>values.iloc[:,:4].min(axis=1))
    dates=pd.to_datetime(frame['TRADE_DATE'],errors='coerce',utc=True).dt.tz_convert('Asia/Ho_Chi_Minh').dt.date
    result.update(invalid_ohlcv=int(bad.sum()),invalid_dates=int(dates.isna().sum()),
                  duplicate_dates=int(dates.dropna().duplicated().sum()),future_dates=int((dates.dropna()>today).sum()),
                  zero_volume=int((v==0).sum()))
    labels=frame.get('QUALITY_STATUS',pd.Series('UNKNOWN',index=frame.index)).fillna('UNKNOWN').astype(str)
    result['quality_labels']={str(k):int(v) for k,v in labels.value_counts().items()}
    result['unverified_rows']=int((~(labels.eq('VALID') | labels.str.startswith('WARNING'))).sum())
    result['warning_rows']=int(labels.str.startswith('WARNING').sum())
    result['sources']=sorted(frame.get('SOURCE',pd.Series('UNKNOWN',index=frame.index)).fillna('UNKNOWN').astype(str).unique().tolist())
    result['adj_close_missing']=int(pd.to_numeric(frame.get('ADJ_CLOSE',pd.Series(np.nan,index=frame.index)),errors='coerce').isna().sum())
    ordered=pd.DataFrame({'date':dates,'close':c}).dropna().sort_values('date')
    result['large_moves']=int((ordered['close'].pct_change(fill_method=None).abs()>0.20).sum())
    if not ordered.empty:
        last=ordered['date'].iloc[-1];result['last_date']=last.isoformat()
        result['elapsed_weekdays']=max(0,int(np.busday_count((last+pd.Timedelta(days=1)).isoformat(),today.isoformat()))) if last<today else 0
    hard=sum(result[k] for k in ['invalid_ohlcv','invalid_dates','duplicate_dates','future_dates'])
    for key,label in [('invalid_ohlcv','OHLCV không hợp lệ'),('invalid_dates','Ngày không hợp lệ'),('duplicate_dates','Trùng ngày'),('future_dates','Ngày tương lai'),('zero_volume','Phiên volume bằng 0'),('unverified_rows','Dòng mang nhãn chưa xác minh'),('warning_rows','Dòng có cảnh báo nguồn'),('adj_close_missing','Thiếu ADJ_CLOSE'),('large_moves','Biến động close trên 20% cần đối chiếu')]:
        if result[key]: result['reasons'].append(f'{label}: {result[key]}')
    if len(result['sources'])>1:result['reasons'].append('Nhiều nguồn trong một chuỗi giá')
    if (result['elapsed_weekdays'] or 0)>=2:result['reasons'].append('Có thể cũ; ngày thường chưa trừ lễ')
    result['status']='INVALID' if hard else ('REVIEW' if result['reasons'] else 'CHECKS_PASSED_NOT_VERIFIED')
    return result

def fingerprint(path):
    p=Path(path).resolve();s=p.stat()
    return {'size_bytes':s.st_size,'mtime_ns':s.st_mtime_ns}

def audit_database(db_path,as_of=None):
    p=Path(db_path).resolve(strict=True)
    today=as_of or pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date().isoformat()
    if Path(str(p)+'-wal').exists() and Path(str(p)+'-wal').stat().st_size:
        raise ValueError('Database có WAL chưa checkpoint; dừng writer trước khi audit.')
    before=fingerprint(p)
    conn=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
    try:
        conn.execute('BEGIN')
        check=[r[0] for r in conn.execute('PRAGMA integrity_check')]
        if check!=['ok']:raise ValueError('SQLite integrity check failed: '+str(check[:3]))
        symbols=pd.read_sql_query('SELECT SYMBOL,EXCHANGE FROM STOCK_SYMBOLS',conn)
        prices_symbols={r[0] for r in conn.execute('SELECT DISTINCT SYMBOL FROM STOCK_PRICES')}
        known=set(symbols['SYMBOL']);rows=[]
        universe=sorted([(str(r.SYMBOL),str(r.EXCHANGE)) for r in symbols.itertuples()]+[(s,'UNKNOWN') for s in prices_symbols-known])
        for position,(symbol,exchange) in enumerate(universe,1):
            df=pd.read_sql_query('SELECT * FROM STOCK_PRICES WHERE SYMBOL=? ORDER BY TRADE_DATE',conn,params=(symbol,))
            rows.append({'symbol':symbol,'exchange':exchange,**assess(df,today)})
            if position % 100 == 0: print(f'Checked {position}/{len(universe)}',flush=True)
        sources=[dict(zip(['source','quality_status','rows'],r)) for r in conn.execute('SELECT SOURCE,QUALITY_STATUS,COUNT(*) FROM STOCK_PRICES GROUP BY SOURCE,QUALITY_STATUS')]
    finally:conn.close()
    after=fingerprint(p)
    if before!=after:raise RuntimeError('Database thay đổi trong khi audit; dừng tiến trình ghi và chạy lại.')
    with p.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if after != fingerprint(p):
        raise RuntimeError('Database thay đổi khi tạo checksum; chạy lại audit.')
    counts={s:sum(r['status']==s for r in rows) for s in ['NO_DATA','INVALID','REVIEW','CHECKS_PASSED_NOT_VERIFIED']}
    return {'schema_version':1,'as_of':str(today),'generated_at':datetime.now(timezone.utc).isoformat(),
            'database_name':p.name,'database_fingerprint':after,'database_sha256':digest,
            'integrity_check':'ok','universe_count':len(rows),'symbols_with_prices':sum(r['bars']>0 for r in rows),
            'total_bars':sum(r['bars'] for r in rows),'status_counts':counts,'source_counts':sources,
            'limitations':['Danh mục trong DB chưa được đối chiếu danh sách niêm yết hiện tại.',
                'VALID là nhãn nhập dữ liệu, không phải chứng nhận giá đúng.',
                'Ngày thường chưa trừ ngày nghỉ lễ; không kết luận mã hủy niêm yết.',
                'Biến động trên 20% chỉ là cờ rà soát; có thể do quyền, thiếu phiên hoặc lỗi.',
                'Chưa đối chiếu giá với nguồn độc lập; price_basis vẫn unknown.'], 'items':rows}

def save_report(report,output):
    p=Path(output);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
    flat=[]
    for item in report['items']:
        row=dict(item)
        for key in ['sources','reasons']:row[key]='; '.join(row[key])
        row['quality_labels']=json.dumps(row['quality_labels'],ensure_ascii=False)
        flat.append(row)
    pd.DataFrame(flat).to_csv(p.with_suffix('.csv'),index=False,encoding='utf-8-sig')


def assert_report_matches(report, db_path):
    """Do not present diagnostics for a different or modified database."""
    path=Path(db_path).resolve(strict=True)
    if Path(str(path)+'-wal').exists() and Path(str(path)+'-wal').stat().st_size:
        raise ValueError('SQLite có WAL đang hoạt động; dừng writer và tạo lại báo cáo.')
    if report.get('database_fingerprint') != fingerprint(path):
        raise ValueError('Database đã đổi hoặc báo cáo thuộc file khác. Chạy lại audit_quality.py.')
    with path.open('rb') as stream:
        actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if report.get('database_sha256') != actual:
        raise ValueError('Checksum database không khớp báo cáo. Chạy lại audit_quality.py.')
