from datetime import date
from pathlib import Path
from typing import Literal
import pandas as pd
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import HTMLResponse,Response
from pydantic import BaseModel,Field,ConfigDict
from src.phase7 import service,store
from src.phase7.data import snapshot,reference,benchmark,safe,valid
from src.phase7.features import features
from src.phase7.model import walk_forward,sensitivity
from src.phase7.portfolio import simulate
from src.phase7.reports import pdf_bytes,csv_bytes
router=APIRouter()
def path():
    from src.web.app import get_repo,FORCE_MOCK
    if not FORCE_MOCK:raise HTTPException(409,'Phase 7 mới hỗ trợ SQLite; dùng giao diện cũ cho Oracle.')
    return get_repo().db_path
def frame(symbol):
    f=snapshot(path())['frames'].get(symbol)
    if f is None or not valid(f):raise HTTPException(422,'Mã thiếu hoặc lỗi dữ liệu')
    return f
def user(req):return req.state.user['username']
def call(fn,*args,**kw):
    try:return safe(fn(*args,**kw))
    except (ValueError,KeyError) as e:raise HTTPException(422,str(e))
class Symbol(BaseModel):symbol:str=Field(pattern=r'^[A-Z0-9^][A-Z0-9.^-]{0,19}$')
class ModelRequest(Symbol):
    horizon:Literal[5,10,20]=10
    C:float=Field(default=1,ge=.01,le=10,allow_inf_nan=False)
    threshold:float=Field(default=.55,ge=.5,le=.9,allow_inf_nan=False)
    sensitivity:bool=False
class Compare(BaseModel):symbols:list[str]=Field(min_length=2,max_length=10)
class Portfolio(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    symbols:list[str]=Field(min_length=1,max_length=30)
    capital:float=Field(default=1e8,gt=0,le=1e12)
    max_weight:float=Field(default=.2,gt=0,le=1)
    risk_trade:float=Field(default=.01,gt=0,le=.05)
    risk_total:float=Field(default=.05,gt=0,le=.2)
    atr_multiple:float=Field(default=2,ge=.5,le=10)
    threshold:float=Field(default=60,ge=0,le=100)
    rebalance:int=Field(default=10,ge=1,le=60)
    participation:float=Field(default=.01,gt=0,le=.1)
    fee:float=Field(default=.0015,ge=0,le=.05)
    tax:float=Field(default=.001,ge=0,le=.05)
    slip:float=Field(default=.001,ge=0,le=.05)
    strict:bool=True
class Journal(Symbol):
    model_config=ConfigDict(allow_inf_nan=False)
    entry_date:date
    exit_date:date|None=None
    entry:float=Field(gt=0,le=1e9)
    exit:float|None=Field(default=None,gt=0,le=1e9)
    qty:int=Field(gt=0,le=100000000)
    costs:float=Field(default=0,ge=0,le=1e12)
    notes:str=Field(default='',max_length=2000)
class Filters(BaseModel):
    search:str=Field(default='',max_length=100)
    regime:str=Field(default='',max_length=30)
    min_score:int=Field(default=0,ge=0,le=100)
    sort:Literal['score','symbol','rs_percentile']='score'
class Export(BaseModel):
    kind:Literal['scan','symbol']='scan'
    symbol:str=Field(default='HPG',pattern=r'^[A-Z0-9^][A-Z0-9.^-]{0,19}$')
    format:Literal['pdf','csv']='pdf'
@router.get('/phase7',response_class=HTMLResponse)
def ui():return (Path(__file__).parent/'ui.html').read_text(encoding='utf-8')
@router.get('/api/p7/dashboard')
def dashboard():return call(service.dashboard,path())
@router.get('/api/p7/detail/{symbol}')
def detail(symbol:str):return call(service.detail,path(),symbol.upper())
@router.get('/api/p7/health/{symbol}')
def health(symbol:str):return call(service.health,path(),symbol.upper())
@router.post('/api/p7/model')
def model(req:ModelRequest):
    f=frame(req.symbol);b=benchmark();r=call(walk_forward,f,b,req.horizon,req.C,req.threshold)
    if req.sensitivity:r['sensitivity']=call(sensitivity,f,b,req.horizon)
    return r
@router.post('/api/p7/compare')
def compare(req:Compare):return call(service.compare,path(),req.symbols)
@router.post('/api/p7/portfolio')
def portfolio(req:Portfolio):
    snap=snapshot(path());frames={s:frame(s) for s in dict.fromkeys(req.symbols)};ex=dict(zip(snap['catalog'].SYMBOL,snap['catalog'].EXCHANGE))
    from import_phase7_reference import validate
    cal=reference('calendar');limits=reference('limits');units=reference('units')
    if req.strict:
        for k,f in [('calendar',cal),('limits',limits),('units',units)]:
            try:validate(k,f)
            except ValueError as e:raise HTTPException(409,'STRICT: '+str(e))
        if not set(req.symbols)<=set(units.SYMBOL):raise HTTPException(409,'STRICT: thiếu RAW/VND cho mã')
    return call(simulate,frames,ex,**req.model_dump(exclude={'symbols'}),calendar=pd.to_datetime(cal.DATE) if 'DATE' in cal else None,limits=limits if not limits.empty else None,benchmark=benchmark())
@router.get('/api/p7/watch')
def watches(request:Request):return store.watches(user(request))
@router.post('/api/p7/watch')
def watch(req:Symbol,request:Request):
    rows=store.watches(user(request))
    if len(rows)>=100 and req.symbol not in {r['symbol'] for r in rows}:raise HTTPException(422,'Tối đa 100 mã')
    frame(req.symbol);store.watch(user(request),req.symbol);return {'ok':True}
@router.post('/api/p7/watch/remove')
def unwatch(req:Symbol,request:Request):store.watch(user(request),req.symbol,True);return {'ok':True}
@router.post('/api/p7/alerts/poll')
def poll(request:Request):
    states={}
    for w in store.watches(user(request)):
        try:
            d=service.detail(path(),w['symbol'])['daily'];states[w['symbol']]={'regime':d['regime'],'breakout':d['breakout'],'score_band':int((d['adaptive_score'] or 0)//10)}
        except ValueError:states[w['symbol']]={'status':'NO_VALID_DATA'}
    return store.poll(user(request),states)
@router.get('/api/p7/journal')
def journal(request:Request):return store.journal(user(request))
@router.post('/api/p7/journal')
def add_trade(req:Journal,request:Request):
    today=pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date()
    if req.entry_date>today or (req.exit_date and (req.exit_date<req.entry_date or req.exit_date>today)) or ((req.exit is None)!=(req.exit_date is None)):raise HTTPException(422,'Ngày/giá thoát không hợp lệ')
    r=req.model_dump(mode='json');r['net_pnl']=(req.exit-req.entry)*req.qty-req.costs if req.exit is not None else None
    f=frame(req.symbol);prior=f.loc[f.TRADE_DATE<pd.Timestamp(req.entry_date)];r['signal_before_entry']=None
    if len(prior)>=200:
        i=features(prior).iloc[-1];r['signal_before_entry']=safe({'as_of':str(prior.TRADE_DATE.iloc[-1].date()),'score':i.adaptive_score,'regime':i.regime})
    return store.journal(user(request),r)
@router.get('/api/p7/filters')
def filters(request:Request):return store.filters(user(request))
@router.post('/api/p7/filters')
def save_filters(req:Filters,request:Request):return store.filters(user(request),req.model_dump())
@router.post('/api/p7/export')
def export(req:Export):
    if req.kind=='scan':
        r=call(service.dashboard,path());rows=[{k:x.get(k) for k in ['symbol','as_of','score','regime','status','rs_percentile','sector']} for x in r['items']];notes=[r['scope'],'Xuất tất cả mã có giá, không áp dụng bộ lọc màn hình.']
    else:
        r=call(service.detail,path(),req.symbol);rows=[{'Chỉ tiêu':k,'Giá trị':v} for k,v in r['daily'].items()];notes=[req.symbol+' | '+r['as_of'],*r['warnings']]
    body=pdf_bytes('QuantumTrade Phase 7 - '+req.kind,rows,notes) if req.format=='pdf' else csv_bytes(rows)
    return Response(body,media_type='application/pdf' if req.format=='pdf' else 'text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="qta7-{req.kind}.{req.format}"'})
