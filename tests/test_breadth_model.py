"""Offline tests for multi-provider and rolling 5/20/60-day market breadth."""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0,str(SCRIPTS))
import breadth_model as m

class IndustryTests(unittest.TestCase):
    def test_sina_parse_and_independent_fallback(self):
        payload = {}
        for i in range(40):
            payload[f"new_demo{i}"] = f"new_demo{i},行业{i},35,20,0.1,2.5,100000,10000000,sz000001,1,12,0,某股"
        raw = "var S_Finance_bankuai_sinaindustry = " + json.dumps(payload,ensure_ascii=False) + ";"
        sectors = m.parse_sina_industries(raw)
        self.assertEqual(len(sectors),40)
        self.assertEqual(sectors["sina:new_demo2"]["change_pct"],2.5)
        def failure(url,params,retries=3):
            raise RuntimeError("502")
        result = m.get_industries(failure,lambda x:[], get_sina=lambda: {
            "provider":"sina","taxonomy":"新浪行业分类（非申万）",
            "sectors":sectors,"url":"https://example.org/"
        })
        self.assertEqual(result["provider"],"sina")
        self.assertIn("502"," ".join(result["issues"]))

    def test_rejects_truncated_industry_list(self):
        with self.assertRaises(ValueError):
            m.parse_sina_industries('var x = {"new_a":"new_a,煤炭,12,1,1,2,0,0,0,0,0,0,0"};')

class HistoricalBreadthTests(unittest.TestCase):
    def test_effective_coverage_weights_and_missing(self):
        values=[
            {"weight":.40,"coverage":50,"score":4},
            {"weight":.35,"coverage":0,"score":None},
            {"weight":.25,"coverage":100,"score":2}
        ]
        score,coverage=m.combine(values)
        self.assertEqual(coverage,45)
        self.assertEqual(score,3.0)

    def test_five_day_participation_requires_history(self):
        hist=m.fresh_history()
        start=date(2026,8,3)
        for i in range(4):
            m.update_participation(hist,str(start+timedelta(days=i)),.65,5200,"沪深A")
        self.assertIsNone(m.participation(hist,str(start+timedelta(days=3)))["score"])
        m.update_participation(hist,str(start+timedelta(days=4)),.6,5200,"沪深A")
        res=m.participation(hist,str(start+timedelta(days=4)))
        self.assertEqual(res["score"],3.0)
        self.assertEqual(res["coverage"],100)
        m.update_participation(hist,str(start+timedelta(days=4)),.7,5200,"沪深A")
        self.assertEqual(len(hist["participation"]),5)

    def test_industry_trend_vendor_histories_are_disjoint(self):
        hist=m.fresh_history()
        start=date(2026,1,1)
        sina={"provider":"sina","taxonomy":"新浪行业分类（非申万）",
              "sectors":{f"sina:s{i}":{"name":f"行业{i}","change_pct":1.0 if i<32 else -1.0}
                         for i in range(40)}}
        for i in range(60):
            d=str(start+timedelta(days=i))
            self.assertTrue(m.update_industries(hist,d,sina))
        got=m.industry_trend(hist,d,sina)
        self.assertEqual(got["coverage"],100)
        self.assertEqual(got["sample"],40)
        other={"provider":"eastmoney","taxonomy":"东方财富",
               "sectors":{f"em:BK{i}":{"name":str(i),"change_pct":1} for i in range(40)}}
        self.assertIsNone(m.industry_trend(hist,d,other)["score"])

    def test_stock_history_needs_60_valid_days(self):
        hist=m.fresh_history()
        start=date(2026,1,1)
        quotes={f"{i:06d}":{"price":10+i/10000} for i in range(3600)}
        for j in range(60):
            q={symbol:{"price":x["price"]+j*.01} for symbol,x in quotes.items()}
            self.assertTrue(m.update_stocks(hist,str(start+timedelta(days=j)),q,"full"))
        result=m.stock_trend(hist,str(start+timedelta(days=59)),3600)
        self.assertEqual(result["coverage"],50)
        self.assertEqual(result["sample"],3600)
        self.assertEqual(result["above_ma60"],1.0)
        self.assertFalse(m.update_stocks(hist,str(start+timedelta(days=61)),quotes,"fallback"))

if __name__=="__main__":
    unittest.main()
