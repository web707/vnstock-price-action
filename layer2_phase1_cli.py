import argparse,json
from pathlib import Path
import pandas as pd
from structure_builder_sfs import Config,build_labels
p=argparse.ArgumentParser();p.add_argument('--swings',required=True);p.add_argument('--ohlcv');p.add_argument('--as-of',required=True);p.add_argument('--output',required=True)
a=p.parse_args();out=Path(a.output)
if out.exists():raise SystemExit('Use a NEW output directory to preserve existing snapshots')
r=build_labels(pd.read_csv(a.swings),pd.read_csv(a.ohlcv) if a.ohlcv else None,as_of=a.as_of)
out.mkdir(parents=True)
for key in ['raw','validated','sequence','swing_label','audit','quarantine']:r[key].to_csv(out/(key+'.csv'),index=False)
(out/'batch_log.json').write_text(json.dumps(r['batch_log'],indent=2),encoding='utf-8')
(out/'rule_config.json').write_text(json.dumps(r['config'],indent=2),encoding='utf-8')
print(json.dumps(r['batch_log']))
