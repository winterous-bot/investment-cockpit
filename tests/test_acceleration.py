import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"acceleration"))
from acceleration_model import *
class AccelerationTest(unittest.TestCase):
    def test_calendar(self):
        self.assertEqual(period(latest_common("20261125")),"20260930")
        self.assertEqual(period(latest_common("20270429")),"20260930")
        self.assertEqual(period(latest_common("20270430")),"20270331")
        self.assertEqual(cutoff(qindex("20261231")),"20270430")
    def fixture(self):
        q=qindex("20260930");d={};k="000001.SZ"
        # 3 yoy: 5%, 20%, 40%; margins on current quarter improve.
        qs={q-6:(100e6,10e6),q-5:(100e6,10e6),q-4:(100e6,10e6),
            q-3:(100e6,10e6),q-2:(100e6,10.5e6),q-1:(110e6,12e6),q:(110e6,14e6)}
        for t in range(q-7,q+1):
            r,e=qs.get(t,(100e6,10e6))
            if t%4:prev=d[("income_vip",t-1)][k]["revenue"] if ("income_vip",t-1) in d else 0;pe=d[("fina_indicator_vip",t-1)][k]["profit_dedt"] if ("fina_indicator_vip",t-1) in d else 0;pc=d[("cashflow_vip",t-1)][k]["n_cashflow_act"] if ("cashflow_vip",t-1) in d else 0;pn=d[("income_vip",t-1)][k]["n_income"] if ("income_vip",t-1) in d else 0
            else:prev=pe=pc=pn=0
            d[("income_vip",t)]={k:{"revenue":prev+r,"n_income":pn+e,"comp_type":1}}
            d[("fina_indicator_vip",t)]={k:{"profit_dedt":pe+e}}
            d[("cashflow_vip",t)]={k:{"n_cashflow_act":pc+e}}
        return d,k,q
    def test_quarters_and_gates(self):
        d,k,q=self.fixture();x,r=metrics(d,k,q)
        self.assertEqual(r,"ok");self.assertAlmostEqual(x["growth"],.4);self.assertAlmostEqual(x["prior_growth"],.2);self.assertAlmostEqual(x["acceleration"],.2);self.assertAlmostEqual(x["cash_conversion"],1)
        self.assertEqual(classify(x),"sustained")
        d[("cashflow_vip",q)][k]["n_cashflow_act"]-=50e6
        self.assertEqual(metrics(d,k,q)[1],"cash_gate")
    def test_signals(self):
        self.assertEqual(classify({"growth":.35,"prior_growth":.10,"acceleration":.25,"prior_acceleration":-.1}),"early")
        self.assertIsNone(classify({"growth":.4,"prior_growth":.8,"acceleration":-.4,"prior_acceleration":.1}))
        self.assertEqual(classify({"growth":.5,"prior_growth":.25,"acceleration":.25,"prior_acceleration":.05}),"sustained")
    def test_selection(self):
        p="20260930";row={"ts_code":"000001.SZ","end_date":p,"ann_date":"20261025","profit_dedt":20}
        r,h=select([row,{**row,"ann_date":"20261201","profit_dedt":99}],"fina_indicator_vip",p,"20261125")
        self.assertEqual(r["000001.SZ"]["profit_dedt"],20)
        r,h=select([row,{**row,"profit_dedt":21}],"fina_indicator_vip",p,"20261125")
        self.assertEqual(h["conflicts"],1);self.assertFalse(r)
    def test_outcomes_and_baseline(self):
        a=[{"code":"a","growth":.4,"signal":"early"},{"code":"b","growth":.8,"signal":None},{"code":"c","growth":.2,"signal":"sustained"}]
        s,b=groups(a)["union"];self.assertEqual(len(s),len(b));self.assertEqual(b[0]["code"],"b")
        z=paired_stats(s,b,{"a":.2,"b":.1,"c":-.5})
        self.assertTrue(z["coverage_pass"]);self.assertAlmostEqual(z["signal_median"],-.15)
        self.assertFalse(paired_stats(s,b,{"a":.2})["coverage_pass"])
if __name__=="__main__":unittest.main()
