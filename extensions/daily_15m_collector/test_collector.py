import unittest,sqlite3,tempfile
from contextlib import closing
from pathlib import Path
from collector import collect
class CollectorTests(unittest.TestCase):
 def test_insert_duplicate_invalid_and_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/'q.db'
   bar=dict(ticker='HPG',candle_time='2026-11-05T14:15:00+07:00',open=100,high=105,low=98,close=101,volume=1000)
   x=collect(db,[bar,bar,dict(bar,high=99)],'TEST')
   self.assertEqual((x['inserted'],x['duplicate'],x['invalid']),(1,1,1))
   y=collect(db,[dict(bar,open=999,high=1000)],'TEST')
   self.assertEqual((y['inserted'],y['duplicate']),(0,1))
   with closing(sqlite3.connect(db)) as c:
    self.assertEqual(c.execute('SELECT count(*) FROM candles_15m').fetchone()[0],1)
    self.assertEqual(c.execute('SELECT open FROM candles_15m').fetchone()[0],100)
    self.assertEqual(c.execute('SELECT count(*) FROM fetch_runs').fetchone()[0],2)
 def test_naive_time_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   row=dict(ticker='HPG',candle_time='2026-11-05 09:15',open=1,high=2,low=1,close=2,volume=1)
   self.assertEqual(collect(Path(d)/'a.db',[row],'TEST')['invalid'],1)
if __name__=='__main__':unittest.main(verbosity=2)
