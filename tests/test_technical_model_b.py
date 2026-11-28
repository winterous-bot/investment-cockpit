import unittest
from technical.model_b import *
from technical.model_b_data import cross_section,close_series
from datetime import date as dt,timedelta
class ModelBTest(unittest.TestCase):
    def test_market(self):
        ds=[(dt(2025,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(300)]
        b=[{"date":d,"close":100+i} for i,d in enumerate(ds)]
        x={k:b for k in INDEX_WEIGHTS}
        self.assertEqual(market_trend(x,ds,ds[-1])["score"],5)
        x.pop("932000.CSI");self.assertEqual(market_trend(x,ds,ds[-1])["coverage"],80)
        x.pop("000300.SH");self.assertIsNone(market_trend(x,ds,ds[-1])["score"])
        self.assertIsNone(index_trend(b[:-1],ds,ds[-1])["score"])
        self.assertIsNone(index_trend(b[:-2]+b[-1:],ds,ds[-1])["score"])
    def test_membership(self):
        tax={"801080.SI":"电子","801780.SI":"银行"}
        r=[{"ts_code":"X","l1_code":"801080.SI","in_date":"20220101","out_date":"20260101"},{"ts_code":"X","l1_code":"801780.SI","in_date":"20260101","out_date":None}]
        self.assertEqual(point_membership(r,"X","20251231",tax)["code"],"801080.SI")
        self.assertEqual(point_membership(r,"X","20260101",tax)["code"],"801780.SI")
        self.assertEqual(point_membership(r,"X","20210101",tax)["state"],"unavailable")
        self.assertEqual(point_membership(r[1:],"X","20251231",tax)["state"],"unavailable")
        self.assertEqual(point_membership(r+[dict(r[1],l1_code="801080.SI")],"X","20260101",tax)["state"],"unavailable")
    def test_breadth_gates(self):
        d="20261127"
        p=[dict(id=k,weight=w,score=1,coverage=100,asof=d) for k,w in (("stock",.4),("sector",.35),("participation",.25))]
        self.assertEqual(combine_breadth(p,d)["score"],1)
        p[0]["asof"]="20261126";self.assertIsNone(combine_breadth(p,d)["score"])
        self.assertEqual(eligible_at({"a":("20200101","20250101"),"b":("20260101",None)},"20240101"),{"a"})
    def test_context(self):
        d="20261127";m={"score":1,"asof":d,"coverage":100};b=dict(m);l=dict(m);i={"ready":True,"membership":{"asof":d},"trend":{"asof":d}}
        self.assertEqual(context_gate(m,b,l,i,d)["state"],"defensive")
        b["asof"]="20261126";self.assertEqual(context_gate(m,b,l,i,d)["state"],"incomplete")
        self.assertTrue(context_gate(m,b,l,i,d,True)["block_new_exposure"])
        b.update(asof=d,score=3)
        self.assertEqual(context_gate(m,b,l,i,d)["state"],"context_ready")
        self.assertIsNone(context_gate(m,b,l,i,d)["block_new_exposure"])
        self.assertFalse(context_gate(m,b,l,i,d,False)["block_new_exposure"])
        a={"asof":d,"composite_ready":True,"horizons":{"short":{"D":50}}}
        self.assertEqual(attach(a,m,b,l,i)["horizons"],a["horizons"])
    def test_activity(self):
        ds=[(dt(2025,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(65)]
        s=[{"date":d,"amount":100} for d in ds]
        self.assertEqual(activity(s,s,ds,ds[-1])["score"],4)
        self.assertIsNone(activity(s,s[:-1],ds,ds[-1])["score"])
    def test_cross_section_validation(self):
        r={"ts_code":"600000.SH","trade_date":"20261127","close":10}
        self.assertEqual(cross_section([r],"20261127",("close",)),{"600000.SH":(10.,)})
        with self.assertRaises(ValueError):cross_section([r,r],"20261127",("close",))
        with self.assertRaises(ValueError):cross_section([r],"20261126",("close",))
    def test_missing_breadth(self):
        self.assertIsNone(stock_breadth({}, {}, {}, ["20261127"],"20261127")["score"])
        self.assertIsNone(sector_breadth({},["20261127"],"20261127")["score"])
        self.assertIsNone(participation({}, {}, ["20261127"],"20261127")["score"])
if __name__=="__main__":unittest.main()
