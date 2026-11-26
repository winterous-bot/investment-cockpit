import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"growth"))
import financial_engine as old
import financial_engine_v141 as new
class V141Test(unittest.TestCase):
    def setUp(self):
        self.i={k:0. for k in new.INCOME_OPTIONAL}
        self.i.update(operate_profit=12e8,total_profit=12e8,income_tax=3e8,n_income=9e8,fin_exp_int_exp=2e8,fin_exp_int_inc=1e8,revenue=100e8,invest_income=1e8,ebit=14e8)
        self.c={k:0. for k in new.CF_OPTIONAL}
        self.c.update(n_cashflow_act=12e8,c_pay_acq_const_fiolta=3e8,c_cash_equ_end_period=10e8,im_net_cashflow_oper_act=12e8,depr_fa_coga_dpba=2e8)
        self.b={k:0. for k in new.BS_OPTIONAL}
        self.b.update(total_assets=100e8,total_liab=50e8,total_hldr_eqy_inc_min_int=50e8,total_hldr_eqy_exc_min_int=48e8,money_cap=12e8,minority_int=2e8,st_borr=10e8,lt_borr=5e8,trad_asset=2e8,oth_eqt_tools=1e8)
        self.y=["20231231","20241231","20251231"];self.l="20260930";self.p="20250930"
        self.ins={t:self.i for t in self.y+[self.l,self.p]}
        self.cs={t:self.c for t in ["20221231"]+self.y+[self.l,self.p]}
        self.bs={t:self.b for t in self.cs}
        self.row={"market_cap":100,"roic":.17,"ocf_ttm":12,"revenue_ttm":100,"debt_ratio":.5,"valuation":{"close":20,"share_verified":True}}
    def run_model(self,mod=new):
        return mod.reconstruct(self.row,self.ins,self.cs,self.bs,self.y,self.l,self.p)
    def test_unchanged_solver(self):
        a=self.run_model(old);b=self.run_model()
        self.assertEqual(a["sensitivity"],b["sensitivity"])
        self.assertEqual(a["forward"],b["forward"])
        self.assertAlmostEqual(b["accounting"]["roic_bridge"][-1]["adjusted"],9/53)
        self.assertAlmostEqual(b["accounting"]["roic_bridge"][-1]["no_investment_deduction"],9/55)
        self.cs[self.y[0]]={**self.c,"c_pay_acq_const_fiolta":20e8}
        self.assertEqual(self.run_model()["reason"],"nonpositive_annual_or_ttm_fcff_ebit")
        self.assertEqual(self.run_model()["reason"],self.run_model(old)["reason"])
    def test_signed_minority(self):
        b={**self.b,"total_hldr_eqy_exc_min_int":52e8,"minority_int":-2e8}
        self.bs[self.y[0]]=b
        self.assertEqual(self.run_model(old)["reason"],"minority_equity_mismatch")
        r=self.run_model();self.assertEqual(r["status"],"ok")
        self.assertIn("negative_book_minority",r["accounting"]["warnings"])
        self.bs[self.l]=b
        self.assertEqual(self.run_model()["reason"],"negative_current_minority_requires_review")
        self.bs[self.l]={**b,"minority_int":None}
        self.assertEqual(self.run_model()["reason"],"negative_minority_unconfirmed")
        self.bs[self.l]={**b,"minority_int":2e8}
        self.assertEqual(self.run_model()["reason"],"minority_equity_mismatch")
    def test_missing_and_negative_interest(self):
        self.ins[self.y[0]]={**self.i,"fin_exp_int_exp":None}
        r=self.run_model();self.assertEqual(r["reason"],"missing_fin_exp_int_exp")
        self.assertEqual(r["audit"]["interest"][0]["implied_interest"],2e8)
        self.ins[self.y[0]]={**self.i,"fin_exp_int_exp":-1e8}
        self.assertEqual(self.run_model()["reason"],"invalid_income")
    def test_material_roic_and_negative_assets(self):
        self.row["roic"]=.50
        self.assertIn("roic_gap_material",self.run_model()["accounting"]["warnings"])
        self.bs[self.y[0]]={**self.b,"oth_eq_invest":-1e8}
        r=self.run_model();self.assertEqual(r["reason"],"invalid_debt_or_investments")
        self.assertEqual(r["audit"]["balance"][1]["negative_items"],{"oth_eq_invest":-1e8})
if __name__=="__main__":unittest.main()
