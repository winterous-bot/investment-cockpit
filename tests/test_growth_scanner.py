import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"growth"))
from growth_model import period_plan,select,ttm,cagr,metrics,passes
class GrowthTests(unittest.TestCase):
    def test_period(self):
        p=period_plan("20261125")
        self.assertEqual((p["latest"],p["annual"],p["annual_base"]),("20260930","20251231","20221231"))
        self.assertEqual(period_plan("20260401")["latest"],"20250930")
    def test_revision(self):
        a={"ts_code":"000001.SZ","end_date":"20251231","ann_date":"20260401","f_ann_date":"20260402","report_type":"1","revenue":100}
        rows=[a,{**a,"ann_date":"20261201","revenue":999},{**a,"report_type":"2","revenue":999}]
        d,h=select(rows,"income_vip","20251231","20261125")
        self.assertEqual(d["000001.SZ"]["revenue"],100)
        self.assertEqual(h["future_excluded"],1)
        d,h=select([a,{**a,"revenue":200}],"income_vip","20251231","20261125")
        self.assertFalse(d);self.assertEqual(h["conflicts"],1)
    def test_math(self):
        self.assertEqual(ttm(100,80,60),120)
        self.assertIsNone(ttm(100,None,60))
        self.assertAlmostEqual(cagr(172.8,100,3),.2)
    def test_quality_valuation_separate(self):
        x={"revenue_cagr":.25,"deducted_yoy":.3,"roic":.15,"cash_conversion":1.,"debt_ratio":.4,"pe":80}
        self.assertTrue(passes(x));self.assertFalse(passes(x,valuation=True))
        self.assertFalse(passes({**x,"roic":None}))
    def test_ttm_financials(self):
        p=period_plan("20261125");a=p["annual"];b=p["annual_base"];q=p["prior"];q2=p["prior2"];t=p["latest"];a1=p["annual_prior"]
        k="000001.SZ";d={}
        def put(api,period,**x):d[(api,period)]={k:x}
        for period,revenue,net in [(a,200,20),(b,100,10),(q,150,15),(t,210,25)]:
            put("income_vip",period,revenue=revenue,n_income=net,n_income_attr_p=net,comp_type=1)
        for period,profit in [(a,20),(a1,15),(q,15),(q2,10),(t,25)]:
            put("fina_indicator_vip",period,profit_dedt=profit,roic=15,roe_waa=20)
        for period,ocf in [(a,25),(q,15),(t,30)]:put("cashflow_vip",period,n_cashflow_act=ocf,c_pay_acq_const_fiolta=2)
        put("balancesheet_vip",t,total_assets=100,total_liab=40,total_hldr_eqy_exc_min_int=60)
        x,reason=metrics(k,p,d,{k:{"pe_ttm":30,"total_mv":1000}})
        self.assertEqual(reason,"ok");self.assertAlmostEqual(x["deducted_yoy"],.5);self.assertAlmostEqual(x["cash_conversion"],40/30)
        self.assertTrue(x["valuation_pass"])
if __name__=="__main__":unittest.main()
