"""Exogenous-order replay with conservative, explicitly sourced execution inputs."""
from dataclasses import dataclass,asdict
import math
import numpy as np
import pandas as pd
from src.phase7.portfolio import metrics
from src.phase7.data import safe
from src.phase8.data import members
@dataclass
class Costs:
    fee:float=.0015
    tax:float=.001
    custody_monthly_per_share:float=.27
    margin_annual:float=0.
    margin_limit:float=0.
    slip_base:float=.001
    slip_impact:float=.01
    participation:float=.01
    def validate(self):
        a=list(asdict(self).values())
        if not np.isfinite(a).all() or min(a)<0 or not 0<self.participation<=.1 or self.fee>.05 or self.tax>.05 or self.margin_limit>1 or self.margin_annual>1:raise ValueError('Invalid costs')
def tick(price,exchange):
    if exchange=='HOSE':return 10 if price<10000 else (50 if price<50000 else 100)
    if exchange in ['HNX','UPCOM']:return 100
    raise ValueError('Unknown exchange')
def round_tick(price,exchange,side):
    step=tick(price,exchange);v=(math.ceil(price/step) if side=='BUY' else math.floor(price/step))*step
    # Crossing a price tier must still be a valid tick in the destination tier.
    step=tick(v,exchange);return (math.ceil(v/step) if side=='BUY' else math.floor(v/step))*step

def replay(bars,orders,calendar,universe,actions=None,costs=None,capital=1e8,ideal=False,exercise_rights=False):
    costs=costs or Costs();costs.validate();actions=actions if actions is not None else pd.DataFrame();days=sorted(set(str(pd.Timestamp(d).date()) for d in calendar));idx={d:i for i,d in enumerate(days)}
    if capital<=0 or not np.isfinite(capital) or not days:raise ValueError('Invalid capital/calendar')
    b=bars.copy();b['phase']=b.get('phase','OPEN');required={'symbol','date','phase','open','high','low','close','volume','floor','ceiling'}
    if not required<=set(b) or b.duplicated(['symbol','date','phase']).any():raise ValueError('Invalid bars/schema')
    if any('OPEN' in set(g.phase) and len(g)>1 for _,g in b.groupby(['symbol','date'])):raise ValueError('Không trộn nến ngày OPEN với AM/PM cùng mã/ngày')
    if not set(b.date)<=set(days) or not set(b.phase)<=set(['OPEN','AM','PM']):raise ValueError('Unknown calendar/phase')
    if not np.isfinite(b[['open','high','low','close','volume','floor','ceiling']]).all().all() or (b[['open','high','low','close','floor','ceiling']]<=0).any().any() or (b.volume<0).any() or (b.high<b[['open','close','low']].max(axis=1)).any() or (b.low>b[['open','close']].min(axis=1)).any() or (b.floor>b.ceiling).any():raise ValueError('Invalid OHLC/limits')
    for o in orders:
        if o['date'] not in idx or o['signal_date']>=o['date'] or o['side'] not in ['BUY','SELL'] or o['qty']<=0 or o['qty']%100 or o.get('phase','OPEN') not in ['OPEN','AM','PM']:raise ValueError('Invalid order or look-ahead')
    if not actions.empty and (actions.known_at>actions.ex_date).any():raise ValueError('Unknown action at ex-date')
    cash=float(capital);lots={};marks={};duecash=[];deferred=[];equity=[];fills=[];rejections=[];trades=[];used={}
    def nav():return cash+sum(x[1] for x in duecash)+sum(x['qty']*marks.get(s,0) for s,ll in lots.items() for x in ll)+sum(x['qty']*marks.get(x['symbol'],0) for x in deferred)
    def reject(o,reason):rejections.append({**o,'reason':reason})
    for di,day in enumerate(days):
        elapsed=(pd.Timestamp(day)-pd.Timestamp(days[di-1])).days if di else 0
        if not ideal:
            cash-=max(-cash,0)*costs.margin_annual*elapsed/365
            cash-=sum(x['qty'] for ll in lots.values() for x in ll)*costs.custody_monthly_per_share*elapsed/30
        today=b.loc[b.date==day]
        # Rights use holdings before today's trades, including unsettled shares.
        if not actions.empty:
            for a in actions.loc[actions.ex_date==day].itertuples():
                qty=sum(x['qty'] for x in lots.get(a.symbol,[]))
                if not qty:continue
                if a.kind=='CASH':duecash.append(((a.available_date,2),qty*a.value))
                elif a.kind=='SPLIT':
                    if any(not float(x['qty']*a.value).is_integer() for x in lots[a.symbol]):raise ValueError('Fractional split cần dữ liệu cash-in-lieu')
                    for x in lots[a.symbol]:x['qty']*=a.value;x['cost']/=a.value;x['available']=max(x['available'],(a.available_date,2))
                    if a.symbol in marks:marks[a.symbol]/=a.value
                elif a.kind in ['BONUS','RIGHTS']:
                    newqty=math.floor(qty*a.value)
                    if newqty!=qty*a.value:raise ValueError('Fractional rights cần dữ liệu cash-in-lieu')
                    debit=newqty*a.subscription_price if a.kind=='RIGHTS' else 0
                    if a.kind=='RIGHTS' and (not exercise_rights or cash<debit):rejections.append({'symbol':a.symbol,'date':day,'reason':'rights_not_exercised'});continue
                    cash-=debit;deferred.append({'symbol':a.symbol,'qty':newqty,'cost':a.subscription_price if a.kind=='RIGHTS' else 0,'entered':di,'available':(a.available_date,2)})
        for phase,pn in [('OPEN',0),('AM',1),('PM',2)]:
            now=(day,pn);cash+=sum(v for due,v in duecash if due<=now);duecash=[(due,v) for due,v in duecash if due>now]
            for x in list(deferred):
                if x['available']<=now:lots.setdefault(x['symbol'],[]).append(x);deferred.remove(x)
            for row in today.loc[today.phase==phase].itertuples():marks[row.symbol]=row.open
            for o in [o for o in orders if o['date']==day and o.get('phase','OPEN')==phase]:
                s=o['symbol'];r=today.loc[(today.symbol==s)&(today.phase==phase)]
                if r.empty:reject(o,'missing_session_bar');continue
                r=r.iloc[0];m=members(universe,day);m=m.loc[m.symbol==s]
                if len(m)!=1:reject(o,'missing_point_in_time_membership');continue
                exchange=m.iloc[0].exchange;side=o['side'];qty=int(o['qty'])
                if not ideal:
                    if r.volume<=0:reject(o,'zero_volume');continue
                    if side=='BUY' and r.low>=r.ceiling or side=='SELL' and r.high<=r.floor:reject(o,'locked_limit');continue
                    cap=max(0,int((r.volume*costs.participation-used.get((s,day,phase),0))//100)*100);qty=min(qty,cap)
                if side=='SELL':qty=min(qty,int(sum(x['qty'] for x in lots.get(s,[]) if ideal or x['available']<=now)//100)*100)
                if qty<=0:reject(o,'unsettled_or_volume_cap');continue
                slip=0 if ideal else costs.slip_base+costs.slip_impact*np.sqrt(qty/max(r.volume,1))
                price=r.open*(1+slip if side=='BUY' else 1-slip);price=price if ideal else round_tick(price,exchange,side)
                if not ideal and not max(r.low,r.floor)<=price<=min(r.high,r.ceiling):reject(o,'fill_outside_traded_range');continue
                fee=0 if ideal else costs.fee;tax=0 if ideal else costs.tax
                if side=='BUY':
                    available=cash+(0 if ideal else costs.margin_limit*max(nav(),0));qty=min(qty,int(max(0,available)/(price*(1+fee))//100)*100)
                    if qty<=0:reject(o,'insufficient_cash');continue
                    cash-=qty*price*(1+fee);settle=(days[di+2],2) if di+2<len(days) else ('9999-12-31',2);lots.setdefault(s,[]).append({'qty':qty,'cost':price*(1+fee),'entered':di,'available':now if ideal else settle})
                else:
                    remaining=qty;cost=0.;weighted=0.
                    for x in lots.get(s,[]):
                        if not ideal and x['available']>now:continue
                        take=min(remaining,x['qty']);cost+=take*x['cost'];weighted+=take*(di-x['entered']);remaining-=take;x['qty']-=take
                        if not remaining:break
                    lots[s]=[x for x in lots[s] if x['qty']>0];value=qty*price*(1-fee-tax)
                    if ideal:cash+=value
                    else:duecash.append((((days[di+2] if di+2<len(days) else '9999-12-31'),2),value))
                    trades.append({'symbol':s,'pnl':value-cost,'qty':qty,'holding_sessions':weighted/qty})
                fills.append({**o,'filled_qty':qty,'price':price});used[(s,day,phase)]=used.get((s,day,phase),0)+qty
                if qty<o['qty']:reject({**o,'qty':o['qty']-qty},'unfilled_remainder_cancelled')
            for row in today.loc[today.phase==phase].itertuples():marks[row.symbol]=row.close
        equity.append({'date':day,'equity':nav(),'cash':cash,'receivable':sum(x[1] for x in duecash)})
    initial={'date':str((pd.Timestamp(days[0])-pd.Timedelta(days=1)).date()),'equity':capital,'cash':capital}
    return safe({'mode':'IDEAL' if ideal else 'CONSERVATIVE_REPLAY','metrics':metrics([initial]+equity,trades),'equity':equity,'fills':fills,'rejections':rejections,'costs':asdict(costs),'limitations':['Dữ liệu OPEN là nến ngày: bán tại open sớm nhất T+3; PM T+2 cần nến PM thật.','Giới hạn volume dùng volume cuối phiên: chỉ là giả định năng lực khớp, không mô phỏng hàng đợi intraday.','Profile bước giá hiện tại, chưa có rulebook hiệu lực lịch sử.','Profit factor lệnh chưa phân bổ phí lưu ký/lãi margin/cổ tức; NAV đã tính các khoản này.','Không tự chuyển vị thế qua đổi mã, không định giá thu hồi hủy niêm yết.']})
def compare(*args,**kwargs):
    realistic=replay(*args,**kwargs);ideal=replay(*args,**{**kwargs,'ideal':True})
    return {'realistic':realistic,'ideal':ideal,'return_gap':realistic['metrics']['total_return']-ideal['metrics']['total_return'],'warning':'Cùng lịch đặt lệnh ngoại sinh; không phải hai chiến lược tự tối ưu lại theo vốn.'}
