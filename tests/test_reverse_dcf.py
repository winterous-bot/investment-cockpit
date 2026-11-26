import unittest,sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"growth"))
from reverse_dcf import base_inputs,dcf,solve,analyze,_roots
class ReverseDCFTests(unittest.TestCase):
    def setUp(self):
        self.base={"nopat":10.,"fcff":6.,"roic":.30,"equity":100.,"price":20.,"bridge":5.,"ev":105.}
    def test_normalization_and_bridge(self):
        a=[{"ebit":x*1e8,"fcff":x*.45*1e8,"roic":20} for x in (10,12,15)]
        c={"ebit":13e8,"fcff":5.85e8,"interestdebt":8e8,"netdebt":3e8}
        p={"ebit":11e8,"fcff":4.95e8}
        b={"total_hldr_eqy_inc_min_int":52e8,"total_hldr_eqy_exc_min_int":50e8,"minority_int":2e8,"oth_eqt_tools":1e8}
        row={"market_cap":100,"valuation":{"close":20,"share_verified":True}}
        z,reason=base_inputs(a,c,p,b,row)
        self.assertEqual(reason,"ok")
        self.assertAlmostEqual(z["nopat"],12.75)
        self.assertAlmostEqual(z["fcff"],7.65)
        self.assertAlmostEqual(z["ev"],106)
        self.assertAlmostEqual(z["roic"],.20)
        self.assertEqual(base_inputs(a,{**c,"fcff":-3e8},p,b,row)[1],"nonpositive_annual_or_ttm_fcff_ebit")
        self.assertEqual(base_inputs(a,c,p,{**b,"minority_int":9e8},row)[1],"minority_equity_mismatch")
        self.assertEqual(base_inputs(a,{**c,"netdebt":None},p,b,row)[1],"missing_ev_bridge")
    def test_growth_reinvestment_and_terminal(self):
        b=self.base;n=5;g=.15;w=.10;t=.03
        x=dcf(b,g,n,w,t)
        self.assertAlmostEqual(x["reinvestment"],.5)
        expected=sum(10*(1+g)**i*.5/(1+w)**i for i in range(1,6))+10*(1+g)**n*(1+t)*(1-t/w)/(w-t)/(1+w)**n
        self.assertAlmostEqual(x["ev"],expected)
        self.assertAlmostEqual(x["price"],(expected-5)/100*20)
        self.assertAlmostEqual(x["fcff_cagr"],(10*(1+g)**5*.5/6)**.2-1)
        with self.assertRaises(ValueError):dcf(b,.31,5,w,t)
    def test_inverse_roundtrip(self):
        for n in (5,10):
            for w in (.08,.10,.12):
                for t in (.02,.03,.04):
                    b=self.base.copy()
                    for g in (-.10,0,.08,.18):
                        ev=dcf(b,g,n,w,t)["ev"]
                        s=solve({**b,"ev":ev},n,w,t)
                        self.assertEqual(s["status"],"ok",(n,w,t,g,s))
                        self.assertAlmostEqual(s["nopat_growth"],g,places=5)
    def test_no_solution(self):
        self.assertEqual(solve({**self.base,"ev":1e9},5,.1,.03)["status"],"price_above_model_range")
        self.assertEqual(solve({**self.base,"ev":.001},5,.1,.03)["status"],"price_below_model_range")
    def test_multiple_and_tangent_roots(self):
        b={**self.base,"roic":.05}
        v=dcf(b,.03,5,.12,.03)["ev"]
        self.assertEqual(solve({**b,"ev":v},5,.12,.03)["status"],"ambiguous")
        roots,flat=_roots([.25,-1,1],0,1)
        self.assertFalse(flat);self.assertEqual(len(roots),1);self.assertAlmostEqual(roots[0],.5)
    def test_sensitivity_and_forward(self):
        a=analyze(self.base)
        self.assertEqual(len(a["sensitivity"]),18)
        self.assertEqual(len(a["forward"]),6)
        self.assertEqual(a["forward"][2]["status"],"requires_more_than_100pct_reinvestment")
if __name__=="__main__":unittest.main()
