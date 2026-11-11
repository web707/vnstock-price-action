"""Canonical schema with additive aliases required by the unchanged Layer 2 reader.
CSV/JSON primary timestamps use Vietnam wall time for legacy lexical comparisons;
*_iso and timezone columns preserve timezone explicitly. Missing ATR is empty/NULL.
"""
from pathlib import Path
import numpy as np
import pandas as pd

def export_result(result,path):
    data=result.swings.copy()
    if data.swing_id.isna().any() or data.swing_id.duplicated().any():
        raise ValueError('swing_id must be unique and non-null within the output table')
    for column in ['extreme_time','confirmed_at']:
        data[column+'_iso']=data[column].map(str)
        data[column]=data[column].map(lambda x:x.strftime('%Y-%m-%d %H:%M:%S'))
    data['timezone']=str(result.candles.Datetime.iloc[0].tz) if len(result.candles) else None
    data['atr_at_extreme']=pd.to_numeric(data.atr_at_extreme,errors='coerce').replace([np.inf,-np.inf],np.nan)
    data.loc[data.atr_at_extreme<0,'atr_at_extreme']=np.nan
    aliases={'threshold':'threshold_T','lag_bars':'confirm_delay_bars','vol_over_median':'volume_ratio','source_timeframe':'timeframe'}
    for target,source in aliases.items():data[target]=data[source]
    data['structure_label']=None
    data['pct_change']=data.extreme_price.pct_change()*100
    data['index']=[i for i,t in result.indices];data['confirmed_at_index']=[t for i,t in result.indices]
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix.lower()=='.json':
        path.write_text(data.to_json(orient='records',force_ascii=False,indent=2),encoding='utf-8')
    else:data.to_csv(path,index=False,encoding='utf-8',na_rep='')
