import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"growth"))
from financial_engine import *
class FinancialEngineTest(unittest.TestCase):
    def setUp(self):
        self.i={k:0. for k in INCOME_OPTIONAL}
        self.i.update(operate_profit=12e8,total_profit=12e8,income_tax=3e8,n_income=9e8,fin_exp_int_exp=2e8,fin_exp_int_inc=1e8,revenue=100e8,invest_income=1e8)
        self.c={k:0. for k in CF_OPTIONAL}
        self.c.update(n_cashflow_act=12e8,c_pay_acq_const_fiolta=3e8,c_cash_equ_end_period=10e8,im_net_cashflow_oper_act=12e8,depr_fa_coga_dpba=2e8)
        self.b={k:0. for k in BS_OPTIONAL}
        self.b.update(total_assets=100e8,total_liab=50e8,total_hldr_eqy_inc_min_int=50e8,total_hldr_eqy_exc_min_int=48e8,money_cap=12e8,minority_int=2e8,st_borr=10e8,lt_borr=5e8,trad_asset=2e8,oth_eqt_tools=1e8)
    def test_income_and_cash(self):
        i=operating(self.i);self.assertAlmostEqual(i["ebit"],12e8)
        f=flow(i,self.c,.25);self.assertAlmostEqual(f["nopat"],9e8)
        self.assertAlmostEqual(f["fcff"],7.75e8)
        self.assertAlmostEqual(f["accrual_fcff"],8e8)
        self.assertRaises(ValueError,operating,{**self.i,"fin_exp_int_exp":None})
        self.assertRaises(ValueError,flow,i,{**self.c,"n_cashflow_act":None},.25)
        self.assertRaises(ValueError,flow,i,{**self.c,"im_net_cashflow_oper_act":1e8},.25)
    def test_capital_and_balance_identity(self):
        c=capital(self.b,self.c);self.assertAlmostEqual(c["ic"],53e8)
        self.assertAlmostEqual(c["debt"],15e8)
        self.assertAlmostEqual(c["cash"],10e8)
        self.assertRaises(ValueError,capital,{**self.b,"total_assets":102e8},self.c)
        self.assertRaises(ValueError,capital,{**self.b,"minority_int":5e8},self.c)
    def test_revision_selection(self):
        f=("a","b");base={"ts_code":"000001.SZ","end_date":"20251231","ann_date":"20260401","f_ann_date":"20260402","report_type":"1","comp_type":"1","update_flag":"1","a":1,"b":2}
        def run(rows):return pick(rows,"20251231","20261125",f)[0]
        self.assertEqual(run([base,{**base,"b":None}])["000001.SZ"],{"a":1.,"b":2.})
        self.assertFalse(run([base,{**base,"b":3}]))
        self.assertEqual(run([base,{**base,"b":3,"update_flag":"0"}])["000001.SZ"]["b"],2)
        self.assertFalse(run([{**base,"f_ann_date":"20261201"}]))
        self.assertFalse(run([{**base,"report_type":"6"}]))
        self.assertFalse(run([{k:v for k,v in base.items() if k!="a"}]))
        self.assertFalse(run([{**base,"a":None},{**base,"b":None}]))
    def test_reconstruction_and_model_gate(self):
        years=["20231231","20241231","20251231"];latest="20260930";prior="20250930"
        periods=years+[latest,prior]
        row={"market_cap":100,"roic":.17,"ocf_ttm":12,"revenue_ttm":100,"debt_ratio":.5,"valuation":{"close":20,"share_verified":True}}
        ins={t:self.i for t in periods};cs={t:self.c for t in ["20221231"]+periods};bs={t:self.b for t in cs}
        r=reconstruct(row,ins,cs,bs,years,latest,prior)
        self.assertEqual(r["status"],"ok",r)
        self.assertAlmostEqual(r["base"]["fcff"],7.75)
        self.assertAlmostEqual(r["base"]["roic"],9/53)
        self.assertAlmostEqual(r["base"]["ev"],106)
        self.assertAlmostEqual(r["base"]["tax"],.25)
        self.assertEqual(len(r["sensitivity"]),18)
        r2=reconstruct({**row,"ocf_ttm":1},ins,cs,bs,years,latest,prior)
        self.assertEqual(r2["category"],"data")
        self.assertEqual(r2["reason"],"base_scan_mismatch_ocf_ttm")
        neg={**self.c,"c_pay_acq_const_fiolta":20e8}
        r3=reconstruct(row,ins,{**cs,years[0]:neg},bs,years,latest,prior)
        self.assertEqual(r3["category"],"model")
        self.assertEqual(r3["reason"],"nonpositive_annual_or_ttm_fcff_ebit")
        self.assertIn("accounting",r3)
    def test_optional_blanks_and_no_fabrication(self):
        z=operating({**self.i,"asset_disp_income":None})
        self.assertEqual(z["optional_blanks"],1)
        self.assertRaises(ValueError,operating,{k:v for k,v in self.i.items() if k!="asset_disp_income"})
        self.assertIsNone(flow(operating(self.i),{**self.c,"decr_oper_payable":None},.25)["accrual_fcff"])
if __name__=="__main__":unittest.main()
