from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.responses import HTMLResponse,Response
from pydantic import BaseModel,Field
from typing import Literal
from src.phase7.api import path,call
from src.phase8 import service,research,fast,data
router=APIRouter()
class Research(BaseModel):
    symbols:list[str]=Field(default=['HPG','FPT','VNM','VCB','SSI','MWG'],min_length=1,max_length=40)
    horizon:Literal[5,10,20]=10
    C:float=Field(default=1,ge=.01,le=10,allow_inf_nan=False)
    threshold:float=Field(default=.55,ge=.5,le=.9,allow_inf_nan=False)
    mode:Literal['rolling','expanding']='expanding'
    embargo:int=Field(default=10,ge=5,le=100)
@router.get('/phase8',response_class=HTMLResponse)
def ui():return (Path(__file__).parent/'ui.html').read_text(encoding='utf-8')
@router.get('/api/p8/dashboard')
def dashboard():return call(fast.scan,path())
@router.get('/api/p8/health')
def health():return call(service.health,path())
@router.get('/api/p8/health.csv')
def health_csv():
    import pandas as pd
    body=pd.DataFrame(service.health(path())['items']).to_csv(index=False).encode('utf-8-sig')
    return Response(body,media_type='text/csv',headers={'Content-Disposition':'attachment; filename=qta8-health.csv'})
@router.get('/api/p8/update-plan.csv')
def plan_csv():return Response(data.update_plan(path()).to_csv(index=False).encode('utf-8-sig'),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=qta8-update-plan.csv'})
@router.post('/api/p8/research')
def model(req:Research):return call(research.run,path(),**req.model_dump())
@router.post('/api/p8/replay')
def replay(req:Research):
    r=call(service.replay_data,path(),req.symbols)
    if r.get('status')=='BLOCKED':raise HTTPException(409,r)
    return r
