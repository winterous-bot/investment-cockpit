import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/"company"),str(ROOT/"growth")]
from company_model import *
class CompanyModelTest(unittest.TestCase):
    def test_quarter_differencing(self):
        d={("income_vip","20260331"):{"revenue":100e6},("income_vip","20260630"):{"revenue":240e6}}
        self.assertEqual(quarter(d,qindex("20260630"))["revenue"],140e6)
        self.assertIsNone(quarter(d,qindex("20260930"))["revenue"])
    def test_fcf_cash_and_loss(self):
        a={k:None for k in FLOW};a.update(revenue=100e6,cost=60e6,deducted_profit=-5e6,net_profit=-5e6,cfo=10e6,capex=12e6)
        r=describe_flow(a);self.assertAlmostEqual(r["gross_margin"],.4);self.assertIsNone(r["cash_conversion"]);self.assertAlmostEqual(r["fcf_proxy"],-.02)
    def test_acceleration(self):
        q=[{"deducted_yoy":g,"base_profit":.2,"base_margin":.05,"deducted_profit":.3} for g in (.1,.2,.4)]
        self.assertEqual(acceleration(q)["label"],"持续加速")
        q[0]["base_profit"]=.01;self.assertEqual(acceleration(q)["status"],"low_base")
    def test_unknown_flags(self):
        t={};r=risk_flags(t,{}, {}, {},[{}, {}, {}])
        self.assertTrue(all(x["status"]=="unknown" for x in r))
    def test_ttm_and_annual_length(self):
        p=profile({},period_plan("20261125"))
        self.assertEqual(len(p["annual"]),5);self.assertEqual(len(p["quarters"]),12)
        self.assertIsNone(p["ttm"]["revenue"]);self.assertEqual(p["acceleration"]["status"],"unavailable")
if __name__=="__main__":unittest.main()
