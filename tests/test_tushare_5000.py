"""Offline tests for Tushare 5000-point unified market-data collector."""
import json
import math
import os
import sys
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import tushare_5000 as m
import breadth_model as bm


class FakeResponse:
    def __init__(self,data):
        self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n=4500000):return json.dumps(self.data).encode("utf-8")


class TushareClientTests(unittest.TestCase):
    def test_sample_permission_check_and_token_redaction(self):
        seen=[]
        def request(req,timeout=28):
            data=json.loads(req.data.decode("utf-8"))
            seen.append(data["api_name"])
            self.assertEqual(data["token"],"DUMMY_ONLY")
            return FakeResponse({"code":0,"data":{"fields":["ts_code","close"],"items":[["801010.SI",2100.5]]}})
        api=m.Tushare("DUMMY_ONLY",request=request)
        rows=api.ask("sw_daily",{"trade_date":"20261116"},"ts_code,close")
        self.assertEqual(rows[0]["ts_code"],"801010.SI")
        self.assertEqual(api.status["sw_daily"]["state"],"ok")
        self.assertEqual(api.status["sw_daily"]["rows"],1)
        self.assertEqual(seen,["sw_daily"])
        def invalid(req,timeout=28):
            return FakeResponse({"code":-2001,"msg":"DUMMY_ONLY access denied"})
        api=m.Tushare("DUMMY_ONLY",request=invalid)
        with self.assertRaises(m.SafeAPIError) as caught:
            api.ask("adj_factor",{"trade_date":"20261116"})
        self.assertNotIn("DUMMY_ONLY",str(caught.exception))

    def test_sw2021_level_one_only(self):
        rows=[{"index_code":f"801{i:03d}","industry_name":f"行业{i}",
               "level":"L1","is_pub":"1","src":"SW2021"} for i in range(31)]
        rows.append({"index_code":"801011","industry_name":"二级","level":"L2"})
        api=type("API",(),{"status":{"index_classify":{}},
                            "ask":lambda self,*a,**k:rows})()
        codes=m.sw_level1(api)
        self.assertEqual(len(codes),31)
        self.assertTrue(all(c.endswith(".SI") for c in codes))

    def test_sw_daily_trend_from_true_closes(self):
        asof=date(2026,10,30)
        ds=[(asof-timedelta(days=i)).strftime("%Y%m%d") for i in range(100,-1,-1)]
        # 60 sessions must be explicit and jointly aligned.
        valid=ds[-80:]
        latest=valid[-1]
        sectors={f"801{i:03d}.SI":f"行业{i}" for i in range(31)}
        by_sector={key:[{"trade_date":d,"close":100+j*0.5,
                          "pct_change":0.5} for j,d in enumerate(valid)]
                   for key in sectors}
        class Mock:
            status={"sw_daily":{}}
            def ask(self,name,p,f):
                return by_sector[p["ts_code"]]
        result=m.sw_sector_breadth(Mock(),sectors,valid,latest)
        self.assertEqual(result["score"],5.0)
        self.assertEqual(result["sample"],31)
        self.assertEqual(result["coverage"],100)
        self.assertEqual(result["asof"],m.date_fmt(latest))

    def test_missing_sector_is_not_counted_as_available(self):
        latest="20261116"
        class Mock:
            status={"sw_daily":{}}
            def ask(self,*args,**kwargs):return []
        codes={f"801{i:03d}.SI":str(i) for i in range(31)}
        result=m.sw_sector_breadth(Mock(),codes,["20261116"]*80,latest)
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage"],0)


class AdjustedStockTests(unittest.TestCase):
    def test_adjusted_prices_remove_fake_ex_dividend_shock(self):
        ds=[(date(2026,6,1)+timedelta(days=i)).strftime("%Y-%m-%d") for i in range(80)]
        stock_data={f"{i:06d}":[10+j*0.02 for j in range(79)]+[5.6]
                    for i in range(3600)}
        history={"stock_dates":ds,"stock_prices":stock_data}
        # Ex-dividend last-day adjusted factor doubles, keeping economic trend smooth.
        class Mock:
            status={"adj_factor":{}}
            def ask(self,name,p,f):
                factor=2.0 if p["trade_date"]==ds[-1].replace("-","") else 1.
                return [{"ts_code":f"{i:06d}.SZ","adj_factor":factor}
                        for i in range(3600)]
        listed={f"{i:06d}.SZ" for i in range(3600)}
        result=m.adjusted_stock_breadth(Mock(),history,ds[-1].replace("-",""),
                                        {d.replace("-","") for d in ds},listed)
        self.assertEqual(result["sample"],3600)
        self.assertEqual(result["coverage"],100)
        self.assertGreaterEqual(result["above_ma60"],0.99)

    def test_partial_history_is_rejected(self):
        with self.assertRaises(m.SafeAPIError):
            m.adjusted_stock_breadth(object(),{"stock_dates":[]}, "20261116",set(),set())


class AggregationTests(unittest.TestCase):
    def test_aggregate_coverage_not_inflated(self):
        components=[
            {"weight":.40,"score":4.0,"coverage":100},
            {"weight":.35,"score":None,"coverage":0},
            {"weight":.25,"score":2.0,"coverage":100},
        ]
        score,cov=bm.combine(components)
        self.assertEqual(cov,65)
        self.assertEqual(score,3.0)


if __name__=="__main__":
    unittest.main()
