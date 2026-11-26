import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"growth"))
import financial_engine_v141 as old
import financial_engine_v142 as new

class CapitalClassificationTest(unittest.TestCase):
    def setUp(self):
        self.i={k:0. for k in new.INCOME_OPTIONAL}
        self.i.update(operate_profit=12e8,total_profit=12e8,income_tax=3e8,n_income=9e8,fin_exp_int_exp=2e8,fin_exp_int_inc=1e8,revenue=100e8,invest_income=1e8)
        self.c={k:0. for k in new.CF_OPTIONAL}
        self.c.update(n_cashflow_act=12e8,c_pay_acq_const_fiolta=3e8,c_cash_equ_end_period=10e8,im_net_cashflow_oper_act=12e8,depr_fa_coga_dpba=2e8)
        self.b={k:0. for k in new.BS_OPTIONAL}
        self.b.update(total_assets=100e8,total_liab=50e8,total_hldr_eqy_inc_min_int=50e8,total_hldr_eqy_exc_min_int=48e8,money_cap=12e8,minority_int=2e8,st_borr=10e8,lt_borr=5e8,trad_asset=2e8,lt_eqt_invest=6e8,oth_eq_invest=1e8,oth_illiq_fin_assets=1e8,debt_invest=3e8,oth_debt_invest=2e8,oth_eqt_tools=1e8)
        self.y=["20231231","20241231","20251231"];self.l="20260930";self.p="20250930"
        self.ins={t:self.i for t in self.y+[self.l,self.p]}
        self.cs={t:self.c for t in ["20221231"]+self.y+[self.l,self.p]}
        self.bs={t:self.b for t in self.cs}
        self.row={"market_cap":100,"roic":.17,"ocf_ttm":12,"revenue_ttm":100,"debt_ratio":.5,"valuation":{"close":20,"share_verified":True}}
    def run_model(self,mod=new):return mod.reconstruct(self.row,self.ins,self.cs,self.bs,self.y,self.l,self.p)
    def test_classification_and_bridge(self):
        a=old.capital(self.b,self.c);b=new.capital(self.b,self.c)
        self.assertAlmostEqual(a["ic"],40e8)
        self.assertAlmostEqual(b["ic"],50e8)
        self.assertAlmostEqual(b["investments"],5e8)
        self.assertAlmostEqual(b["retained_investments"],10e8)
        self.assertAlmostEqual(sum(b["investment_items"].values()),15e8)
        x=self.run_model(old);y=self.run_model()
        self.assertEqual(y["status"],"ok")
        self.assertAlmostEqual(x["base"]["ev"],93)
        self.assertAlmostEqual(y["base"]["ev"],103)
        self.assertAlmostEqual(x["base"]["roic"],9/40)
        self.assertAlmostEqual(y["base"]["roic"],9/50)
        self.assertEqual(x["base"]["nopat"],y["base"]["nopat"])
        self.assertEqual(x["base"]["fcff"],y["base"]["fcff"])
        self.assertEqual(x["accounting"]["ttm"],y["accounting"]["ttm"])
        self.assertEqual(y["accounting"]["roic_bridge"][-1]["v141_all_investments_deducted"],x["accounting"]["roics"][-1])
        self.assertIn("material_unclassified_investments",y["accounting"]["warnings"])
    def test_no_change_without_retained_investments(self):
        self.bs={t:{**self.b,**{k:0 for k in new.RETAIN_INVEST_FIELDS}} for t in self.bs}
        a=self.run_model(old);b=self.run_model()
        self.assertEqual(a["sensitivity"],b["sensitivity"])
        self.assertEqual(a["forward"],b["forward"])
    def test_gates_still_enforced(self):
        self.cs[self.y[0]]={**self.c,"c_pay_acq_const_fiolta":20e8}
        self.assertEqual(self.run_model()["reason"],"nonpositive_annual_or_ttm_fcff_ebit")
        self.cs[self.y[0]]=self.c
        self.ins[self.y[0]]={**self.i,"fin_exp_int_exp":None}
        self.assertEqual(self.run_model()["reason"],"missing_fin_exp_int_exp")
        self.ins[self.y[0]]=self.i
        self.bs[self.l]={**self.b,"total_hldr_eqy_exc_min_int":52e8,"minority_int":-2e8}
        self.assertEqual(self.run_model()["reason"],"negative_current_minority_requires_review")
    def test_investment_blank_and_negative(self):
        c=new.capital({**self.b,"trad_asset":None},self.c)
        self.assertIn("trad_asset",c["investment_blank_items"])
        self.assertRaises(ValueError,new.capital,{**self.b,"lt_eqt_invest":-1},self.c)
    def test_positive_capital_restored_by_classification(self):
        b={**self.b,"lt_eqt_invest":50e8}
        self.assertRaises(ValueError,old.capital,b,self.c)
        self.assertGreater(new.capital(b,self.c)["ic"],0)
if __name__=="__main__":unittest.main()
