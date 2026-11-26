import importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"company"),str(ROOT/"growth"),str(ROOT/"scripts")]
spec=importlib.util.spec_from_file_location("company_validation_build",ROOT/"company/build.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PeriodRecoveryTest(unittest.TestCase):
    def row(self,profit,ann="20261030"):
        return {"ts_code":"000001.SZ","end_date":"20260930","ann_date":ann,"profit_dedt":profit,"roic":10,"roe_waa":15,"grossprofit_margin":30}
    class API:
        def __init__(self,rows):self.rows=rows;self.calls=[]
        def ask(self,ep,params,fields):
            self.calls.append((ep,params));return self.rows
    def test_recover_missing(self):
        a=self.API([self.row(100)])
        rows,h=m.repair_period(a,"fina_indicator_vip","000001.SZ","20260930","20261125",[],"x")
        self.assertEqual(h["before"],["profit_dedt"]);self.assertEqual(h["after"],[])
        self.assertEqual(a.calls,[("fina_indicator",{"ts_code":"000001.SZ","period":"20260930"})])
    def test_conflict_not_replaced(self):
        a=self.API([self.row(100)])
        rows,h=m.repair_period(a,"fina_indicator_vip","000001.SZ","20260930","20261125",[self.row(100),self.row(200)],"x")
        self.assertEqual(h["after"],["profit_dedt"]);self.assertGreater(h["growth_conflicts"],0)
    def test_future_not_used(self):
        a=self.API([self.row(100,"20261201")])
        rows,h=m.repair_period(a,"fina_indicator_vip","000001.SZ","20260930","20261125",[],"x")
        self.assertEqual(h["after"],["profit_dedt"])
    def test_complete_not_refetched(self):
        a=self.API([])
        rows,h=m.repair_period(a,"fina_indicator_vip","000001.SZ","20260930","20261125",[self.row(100)],"x")
        self.assertIsNone(h);self.assertEqual(a.calls,[])
if __name__=="__main__":unittest.main()
