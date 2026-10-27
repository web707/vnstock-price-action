"""Cash-only daily simulator: signals at close, orders next session, conservative T+2."""
import numpy as np
import pandas as pd
from src.phase7.features import features
from src.phase7.model import bootstrap

def metrics(equity,trades):
    if not equity:return {}
    v=np.array([r['equity'] for r in equity],float);d=pd.to_datetime([r['date'] for r in equity]);r=pd.Series(v).pct_change().dropna();years=(d[-1]-d[0]).days/365.25
    losses=-sum(min(t['pnl'],0) for t in trades);wins=sum(max(t['pnl'],0) for t in trades);down=np.minimum(r.to_numpy(),0)
    return {'total_return':v[-1]/v[0]-1,'cagr':(v[-1]/v[0])**(1/years)-1 if years>=1 else None,'sharpe':r.mean()/r.std(ddof=1)*np.sqrt(252) if len(r)>1 and r.std(ddof=1)>1e-12 else None,'sortino':r.mean()/np.sqrt(np.mean(down**2))*np.sqrt(252) if len(down) and np.mean(down**2)>1e-16 else None,'max_drawdown':(v/np.maximum.accumulate(v)-1).min(),'profit_factor':wins/losses if losses>0 else None,'expectancy_vnd':np.mean([t['pnl'] for t in trades]) if trades else None,'win_rate':sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,'closed_trades':len(trades),'holding_sessions_mean':np.mean([t['holding_sessions'] for t in trades]) if trades else None}

def simulate(frames,exchanges,capital=1e8,max_weight=.2,risk_trade=.01,risk_total=.05,atr_multiple=2.,threshold=60,rebalance=10,participation=.01,fee=.0015,tax=.001,slip=.001,calendar=None,limits=None,strict=True,benchmark=None):
    if not frames:raise ValueError('Không có dữ liệu')
    if strict and (calendar is None or limits is None):raise ValueError('STRICT cần calendar.csv và limits.csv')
    nums=[capital,max_weight,risk_trade,risk_total,atr_multiple,threshold,rebalance,participation,fee,tax,slip]
    if not np.isfinite(nums).all() or not (capital>0 and 0<max_weight<=1 and 0<risk_trade<=.05 and 0<risk_total<=.2 and atr_multiple>0 and 0<=threshold<=100 and rebalance>=1 and 0<participation<=.1 and all(0<=v<=.05 for v in (fee,tax,slip))):raise ValueError('Thông số không hợp lệ')
    data={};all_days=set()
    for s,frame in frames.items():
        f=frame.sort_values('TRADE_DATE').reset_index(drop=True).copy();i=features(f)
        f['score']=i.adaptive_score;f['atr']=i.atr14;f['average']=i.avg_volume20;f['prior_volume']=i.avg_volume20.shift();f['prior_close']=f.CLOSE_PRICE.shift()
        f.TRADE_DATE=pd.to_datetime(f.TRADE_DATE).dt.normalize();data[s]={r.TRADE_DATE:r for r in f.itertuples(index=False)};all_days.update(data[s])
    days=sorted(all_days) if calendar is None else sorted(d for d in set(pd.DatetimeIndex(calendar).normalize()) if min(all_days)<=d<=max(all_days))
    rules={}
    if limits is not None:
        if limits.duplicated(['DATE','SYMBOL']).any():raise ValueError('Trùng price limits')
        rules={(pd.Timestamp(r.DATE).normalize(),r.SYMBOL):(float(r.FLOOR),float(r.CEILING)) for r in limits.itertuples()}
    def bounds(s,d,prev):
        if (d,s) in rules:return rules[(d,s)]
        if strict:return None
        band={'HOSE':.07,'HNX':.10,'UPCOM':.15}.get(str(exchanges.get(s,'')).upper())
        return (prev*(1-band),prev*(1+band)) if band and np.isfinite(prev) else None
    cash=float(capital);receivable=[];positions={};marks={};pending={};targets=set();trades=[];equity=[];skips={}
    def skip(k):skips[k]=skips.get(k,0)+1
    def nav():return cash+sum(v for _,v in receivable)+sum(p['qty']*marks[s] for s,p in positions.items())
    if days:equity.append({'date':str((days[0]-pd.Timedelta(days=1)).date()),'equity':capital,'cash':cash})
    for t,day in enumerate(days):
        cash+=sum(v for due,v in receivable if due<=t);receivable=[(due,v) for due,v in receivable if due>t]
        for s,p in list(positions.items()):
            r=data[s].get(day)
            if r is None:continue
            bound=bounds(s,day,r.prior_close)
            if bound is None:skip('missing_price_limits');continue
            floor,ceil=bound
            if s not in targets or r.LOW_PRICE<=p['stop']:
                if t-p['entered']<3:skip('unsettled_shares');continue
                if r.HIGH_PRICE<=floor*1.000001:skip('locked_floor');continue
                if not floor<=r.OPEN_PRICE<=ceil:skip('open_outside_limits');continue
                capacity=min(r.prior_volume,r.VOLUME)*participation
                qty=min(p['qty'],int(capacity//100)*100) if np.isfinite(capacity) else 0
                if qty<=0:skip('illiquid_exit');continue
                base=min(r.OPEN_PRICE,p['stop']) if r.LOW_PRICE<=p['stop'] else r.OPEN_PRICE
                price=max(floor,base*(1-slip))
                if not r.LOW_PRICE<=price<=min(r.HIGH_PRICE,ceil):skip('exit_price_not_traded');continue
                proceeds=qty*price*(1-fee-tax);cost=qty*p['entry']*(1+fee)
                trades.append({'symbol':s,'entry_date':p['entry_date'],'exit_date':str(day.date()),'entry':p['entry'],'exit':price,'qty':qty,'pnl':proceeds-cost,'return':proceeds/cost-1,'holding_sessions':t-p['entered']})
                receivable.append((t+3,proceeds));p['qty']-=qty
                if not p['qty']:del positions[s]
        for s,order in pending.items():
            if s in positions:continue
            r=data[s].get(day)
            if r is None:skip('missing_entry_bar');continue
            bound=bounds(s,day,order['close'])
            if bound is None:skip('missing_price_limits');continue
            floor,ceil=bound
            if r.LOW_PRICE>=ceil*.999999:skip('locked_ceiling');continue
            price=r.OPEN_PRICE*(1+slip)
            if not floor<=r.OPEN_PRICE<=ceil or not max(floor,r.LOW_PRICE)<=price<=min(ceil,r.HIGH_PRICE):skip('entry_price_not_traded');continue
            unitrisk=atr_multiple*order['atr']+price*(2*fee+tax+2*slip);equity_now=nav()
            openrisk=sum(max(0,p['entry']-p['stop']+p['entry']*(2*fee+tax+2*slip))*p['qty'] for p in positions.values())
            qty=int(min(cash/(price*(1+fee)),equity_now*max_weight/(price*(1+fee)),equity_now*risk_trade/unitrisk,max(0,equity_now*risk_total-openrisk)/unitrisk,min(order['volume'],r.VOLUME)*participation)//100)*100
            if qty<=0:skip('cash_risk_liquidity');continue
            cash-=qty*price*(1+fee);positions[s]={'qty':qty,'entry':price,'entered':t,'entry_date':str(day.date()),'stop':max(.01,price-atr_multiple*order['atr'])};marks[s]=price
        pending={}
        for s,p in positions.items():
            r=data[s].get(day)
            if r is not None:
                marks[s]=float(r.CLOSE_PRICE)
                if np.isfinite(r.atr):p['stop']=max(p['stop'],r.CLOSE_PRICE-atr_multiple*r.atr)
        equity.append({'date':str(day.date()),'equity':nav(),'cash':cash,'unsettled_cash':sum(v for _,v in receivable)})
        if t%rebalance==0:
            candidates=[]
            for s,rows in data.items():
                r=rows.get(day)
                if r is not None and np.isfinite(r.score) and r.score>=threshold and r.atr>0 and r.average>0 and r.VOLUME>0 and getattr(r,'QUALITY_STATUS','UNKNOWN')=='VALID':candidates.append((float(r.score),s,r))
            candidates.sort(key=lambda x:(-x[0],x[1]));selected=candidates[:max(1,int(1/max_weight))];targets={s for _,s,_ in selected}
            pending={s:{'atr':r.atr,'close':r.CLOSE_PRICE,'volume':r.average} for _,s,r in selected if s not in positions}
    result={'mode':'STRICT_REFERENCES' if strict else 'APPROXIMATE_RESEARCH','evidence':'chưa có bằng chứng hiệu quả','metrics':metrics(equity,trades),'equity':equity,'trades':trades,'open_positions':positions,'skips':skips,'monte_carlo':bootstrap([t['return'] for t in trades]),'benchmark':None,
        'limitations':['T+2 mô phỏng bảo thủ: bán và tái sử dụng tiền ở open T+3, không mô phỏng buổi chiều T+2.',
        'Rebalance thay tập mã; không ép vị thế đang giữ về tỷ trọng. Giới hạn rủi ro/tỷ trọng chỉ áp dụng khi mở lệnh; gap có thể gây vượt.',
        'Volume ngày thực hiện chỉ là trần khả năng khớp, không chứng minh có thể khớp ở open. Không tick size, room, margin, ATO/ATC.',
        'Approximate dùng close trước và biên độ giả định 7/10/15%; có thể sai UPCoM, ngày quyền hoặc niêm yết mới.',
        'Không xử lý dòng tiền quyền/cổ tức/chia tách. Giá cũ được giữ để định giá vị thế thiếu phiên. Không ép đóng cuối dữ liệu.',
        'Snapshot không là universe point-in-time. Backtest quy tắc này không phải OOS của mô hình logistic.']}
    if benchmark is not None and len(equity)>2:
        ds=pd.to_datetime([r['date'] for r in equity[1:]]);b=benchmark.reindex(ds)
        if b.notna().all():
            be=[{'date':str(ds[0].date()),'equity':capital}]+[{'date':str(d.date()),'equity':float(capital*v/b.iloc[0])} for d,v in b.iloc[1:].items()]
            result['benchmark']={'label':'VN-Index close-to-close, chưa phí/cổ tức; bắt đầu phiên đầu','metrics':metrics(be,[]),'equity':be}
    return result
