import unittest,sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"/"v2d"))
from account_risk import account_risk,CATEGORY_SHOCK
def rules():
    return {"totalCap":120,"debtCap":25,"drawdownCap":25,"clusterCap":65,"singleStressCap":6,
            **{k:{"single":15,"total":65} for k in CATEGORY_SHOCK}}
class TestAccountStress(unittest.TestCase):
    def sample(self,stock=100,debt=20):
        # 10 equally weighted securities, equity exactly 100.
        return [{"id":str(i),"value":stock/10,"category":"quality_growth" if i<5 else "stable_leader","group":str(i%2)} for i in range(10)],100-stock+debt,debt
    def test_exact_loss_and_collateral(self):
        p,c,d=self.sample(120,20)
        x=account_risk(p,c,d,rules(),.25,2)
        self.assertAlmostEqual(x["equity"],100)
        self.assertAlmostEqual(x["uniform_stress_loss_ratio"],.30)
        self.assertAlmostEqual(x["simplified_stressed_collateral_ratio"],4.5)
        self.assertAlmostEqual(x["joint_stock_cap"],1.)
        self.assertFalse(x["allow_new_risk"])
    def test_baseline_never_relaxed(self):
        p,c,d=self.sample()
        self.assertEqual(account_risk(p,c,d,rules(),.15,2)["status"],"invalid")
        x=account_risk(p,c,d,rules(),.20,2)
        self.assertLessEqual(x["joint_stock_cap"],1.20)
        self.assertLessEqual(x["debt_cap_at_actual_stock"],.25)
    def test_coupled_collateral_limit(self):
        p,c,d=self.sample(120,20)
        x=account_risk(p,c,d,rules(),.20,5.)
        self.assertAlmostEqual(x["joint_stock_cap"],5/4.2)
        self.assertAlmostEqual(x["debt_cap_at_actual_stock"],.19)
        self.assertIn("collateral_stress",x["violations"])
    def test_no_debt(self):
        p,c,d=self.sample(80,0)
        x=account_risk(p,c,d,rules(),.20,2.)
        self.assertIsNone(x["simplified_stressed_collateral_ratio"])
        self.assertTrue(x["allow_new_risk"])
    def test_concentration(self):
        x=account_risk([{"id":"one","value":80,"category":"high_beta_growth","group":"tech"}],20,0,rules(),.20,2)
        self.assertIn("single_cap_or_stress",x["violations"])
        self.assertIn("group_cap",x["violations"])
        self.assertAlmostEqual(x["category_severe_loss_ratio"],.4)
    def test_unknown_min_and_stale(self):
        p,c,d=self.sample()
        self.assertFalse(account_risk(p,c,d,rules(),.2)["allow_new_risk"])
        self.assertFalse(account_risk(p,c,d,rules(),.2,2,fresh=False)["allow_new_risk"])
    def test_nonpositive_equity(self):
        p,c,d=self.sample()
        self.assertEqual(account_risk(p,0,100,rules(),.2,2)["status"],"invalid")
if __name__=="__main__":unittest.main()
