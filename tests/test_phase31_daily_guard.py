import pandas as pd
from src.web.market_data import exclude_forming_daily_bar

def test_drop_today_preserve_previous_day():
    df=pd.DataFrame({'TRADE_DATE':['2026-10-20','2026-10-21'], 'OPEN_PRICE':[1,2]})
    safe,count=exclude_forming_daily_bar(df,'1d',now='2026-10-21T14:00:00+07:00')
    assert count==1 and len(safe)==1 and str(safe.iloc[0].TRADE_DATE)=='2026-10-20'

def test_intraday_untouched():
    df=pd.DataFrame({'TRADE_DATE':['2026-10-21']})
    safe,count=exclude_forming_daily_bar(df,'15m',now='2026-10-21T14:00:00+07:00')
    assert count==0 and len(safe)==1
