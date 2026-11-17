"""Offline tests for no-manual-action Tushare daily incremental workflow."""
import os
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import breadth_model as bm
import update_tushare_incremental as inc

class DailyIncrementTests(unittest.TestCase):
    def test_weekday_candidates(self):
        d=inc.latest_candidates(date(2026,11,17))
        self.assertEqual([x.isoformat() for x in d[:2]],["2026-11-17","2026-11-16"])
    def test_no_secret_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as td:
            fp=Path(td)/"history.json"
            fp.write_text('{"version":1,"stock_dates":[],"stock_prices":{},"participation":[],"industries":{}}')
            old=fp.read_text()
            result=inc.append_increment("",history_file=fp)
            self.assertFalse(result["updated"])
            self.assertEqual(old,fp.read_text())
    def test_add_sequential_new_days_and_idempotence(self):
        with tempfile.TemporaryDirectory() as td:
            fp=Path(td)/"history.json"
            hist=bm.fresh_history()
            d=date(2026,11,13)
            quotes={f"{i:06d}":{"price":10+i/10000} for i in range(3600)}
            bm.update_stocks(hist,str(d),quotes,"full")
            fp.write_text(__import__('json').dumps(hist),encoding="utf-8")
            dates_seen=[]
            def fetch(token,day):
                dates_seen.append(str(day))
                return {"day":str(day),"sample":3600,
                        "prices":quotes,"measured":3600,"up_ratio":.55}
            result=inc.append_increment("SYNTHETIC",fetch=fetch,end=date(2026,11,17),history_file=fp)
            self.assertTrue(result["updated"])
            self.assertEqual(result["sessions"],2)
            self.assertEqual(dates_seen,["2026-11-16","2026-11-17"])
            current,_=bm.read_history(fp)
            self.assertEqual(current["stock_dates"][-1],"2026-11-17")
            self.assertEqual(len(current["stock_dates"]),3)
            second=inc.append_increment("SYNTHETIC",fetch=fetch,end=date(2026,11,17),history_file=fp)
            self.assertFalse(second["updated"])
            self.assertEqual(len(bm.read_history(fp)[0]["stock_dates"]),3)

if __name__=="__main__":
    unittest.main()
