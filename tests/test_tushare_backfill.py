"""Offline tests: Tushare backfill uses only the free daily endpoint and no real token."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import backfill_tushare as backfill
import breadth_model as breadth

class FakeResponse:
    def __init__(self, body):
        self.body=body
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def read(self,n=-1):return json.dumps(self.body).encode("utf-8")

class TushareDailyTests(unittest.TestCase):
    def fake_request(self,req,timeout=25):
        body=json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["api_name"],"daily")
        self.assertEqual(body["params"]["trade_date"],"20261116")
        self.assertEqual(body["token"],"DUMMY_NOT_REAL")
        return FakeResponse({"code":0,"data":{
            "fields":["ts_code","trade_date","close","pre_close","pct_chg"],
            "items":[["002475.SZ","20261116",50,48,4.1667],
                     ["600519.SH","20261116",1400,1420,-1.408],
                     ["920001.BJ","20261116",12,10,20]]
        }})
    def test_parses_sh_sz_excludes_bj(self):
        with patch.object(backfill,"MIN_SAMPLE",2):
            rec=backfill.tushare_daily("DUMMY_NOT_REAL",date(2026,11,16),request=self.fake_request)
        self.assertEqual(rec["sample"],2)
        self.assertEqual(rec["measured"],2)
        self.assertAlmostEqual(rec["up_ratio"],.5)
        self.assertIn("002475",rec["prices"])
        self.assertNotIn("920001",rec["prices"])
    def test_provider_errors_do_not_echo_token(self):
        def fail(req,timeout=25):
            return FakeResponse({"code":-2001,"msg":"no permission"})
        with self.assertRaises(backfill.TushareError) as caught:
            backfill.tushare_daily("VERY_PRIVATE_VALUE",date(2026,11,16),request=fail)
        self.assertNotIn("VERY_PRIVATE_VALUE",str(caught.exception))
    def test_calendar_skips_weekends(self):
        days=backfill.prior_weekdays(date(2026,11,16),5)
        self.assertEqual(days[0].isoformat(),"2026-11-16")
        self.assertNotIn(5,{x.weekday() for x in days})
        self.assertNotIn(6,{x.weekday() for x in days})

class BackfillHistoryTests(unittest.TestCase):
    def test_makes_80_day_trend_and_5_day_participation(self):
        anchor=date(2026,7,1)
        recs=[]
        for j in range(85):
            day=(anchor+timedelta(days=j)).isoformat()
            prices={f"{i:06d}":{"price":round(10+i/10000+j*.02,3)}
                    for i in range(3600)}
            recs.append({"day":day,"prices":prices,"sample":3600,
                         "measured":3600,"up_ratio":0.7})
        old=breadth.fresh_history()
        old["industries"]={"sina":{"dates":["2026-06-30"],"returns":{"sina:k":[1.0]}}}
        hist=backfill.build_history(old,recs)
        self.assertEqual(len(hist["stock_dates"]),85)
        self.assertEqual(hist["participation"][-1]["date"],recs[-1]["day"])
        self.assertIn("sina",hist["industries"])
        self.assertGreater(breadth.stock_trend(hist,recs[-1]["day"],3600)["coverage"],0)
        self.assertEqual(breadth.participation(hist,recs[-1]["day"])["coverage"],100)

    def test_no_token_reflected_in_log_without_env(self):
        with patch.dict(os.environ,{"TUSHARE_TOKEN":""}):
            with redirect_stdout(io.StringIO()) as o:
                with self.assertRaises(backfill.TushareError):
                    backfill.run(days=100,delay=0)
            self.assertNotIn("DUMMY_NOT_REAL",o.getvalue())

if __name__=="__main__":
    unittest.main()
