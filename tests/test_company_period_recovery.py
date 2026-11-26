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
    def test_revised_version_selected(self):
        old={**self.row(100),"update_flag":"0"}
        new={**self.row(200),"update_flag":"1"}
        p,b,_,h=m.selection([old,new],"fina_indicator_vip","000001.SZ","20260930","20261125")
        self.assertEqual(p["profit_dedt"],200);self.assertEqual(b["profit_dedt"],200)
        self.assertTrue(h["indicator_version"]["revision_selected"])
    def test_conflicting_revisions_not_chosen(self):
        rows=[{**self.row(n),"update_flag":"1"} for n in (100,200)]
        p,b,_,h=m.selection(rows,"fina_indicator_vip","000001.SZ","20260930","20261125")
        self.assertIsNone(b);self.assertIsNone((p or {}).get("profit_dedt"))
        self.assertEqual(h["indicator_version"]["distinct_profit_values"],2)
    def test_profit_consensus_only_for_profile(self):
        a={**self.row(100),"update_flag":"1"}
        b={**a,"roic":12}
        p,base,_,h=m.selection([a,b],"fina_indicator_vip","000001.SZ","20260930","20261125")
        self.assertEqual(p["profit_dedt"],100);self.assertNotIn("roic",p);self.assertIsNone(base)
    def test_future_revision_not_used(self):
        old={**self.row(100),"update_flag":"0"}
        future={**self.row(200,"20261201"),"update_flag":"1"}
        p,b,_,h=m.selection([old,future],"fina_indicator_vip","000001.SZ","20260930","20261125")
        self.assertEqual(p["profit_dedt"],100)
    def test_unknown_flag_not_overruled(self):
        rows=[{**self.row(100),"update_flag":"1"},self.row(200)]
        p,b,_,h=m.selection(rows,"fina_indicator_vip","000001.SZ","20260930","20261125")
        self.assertIsNone(b);self.assertIsNone((p or {}).get("profit_dedt"))
    def test_latest_date_precedes_revision_preference(self):
        old={**self.row(100,"20261029"),"update_flag":"1"}
        new={**self.row(200),"update_flag":"0"}
        p,b,_,h=m.selection([old,new],"fina_indicator_vip","000001.SZ","20260930","20261125")
        self.assertEqual(p["profit_dedt"],200)
if __name__=="__main__":unittest.main()
