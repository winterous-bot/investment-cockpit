import unittest,sys
from pathlib import Path
from datetime import date,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"/"v2b"))
from validate import signals,objective,metrics,drawdown,active
class ValidationTests(unittest.TestCase):
    def row(self,c="bull",week=False,warning=False):
        return {"candidate":c,"week_end":week,"warning_trigger":warning,"baseline":"bull"}
    def test_weekly_two_and_three(self):
        rows=[self.row(week=True)]+[self.row()]*4+[self.row(week=True)]
        self.assertEqual(signals(rows,"B2")[0]["state"],"unknown")
        self.assertEqual(signals(rows,"B2")[-1]["state"],"bull")
        self.assertEqual(signals(rows,"B3")[-1]["state"],"unknown")
        self.assertEqual(signals(rows+[self.row(week=True)],"B3")[-1]["state"],"bull")
    def test_daily_five(self):
        rows=[self.row()]*5
        self.assertEqual(signals(rows,"B1")[3]["state"],"unknown")
        self.assertEqual(signals(rows,"B1")[4]["state"],"bull")
    def test_alert_immediate_and_delayed_clear(self):
        rows=[self.row(week=True),self.row(week=True),self.row(warning=True),self.row(week=True),self.row()]
        out=signals(rows,"B2")
        self.assertTrue(out[1]["high"]);self.assertFalse(out[2]["high"])
        self.assertTrue(out[3]["alert"]);self.assertTrue(out[4]["high"])
    def test_lower_candidate_freezes_increase(self):
        out=signals([self.row(week=True),self.row(week=True),self.row("range",True)],"B2")
        self.assertTrue(out[-1]["high"]);self.assertFalse(out[-1]["new_high"])
    def test_unknown_evidence(self):
        out=signals([self.row(week=True),self.row("unknown",True),self.row(week=True)],"B2")
        self.assertEqual(out[-1]["state"],"unknown")
    def test_direction_risk_separate(self):
        days=[(date(2024,1,1)+timedelta(days=i)).isoformat() for i in range(181)]
        C=[1.]*120+[1.+.004*i for i in range(61)]
        idx={k:C.copy() for k in active(days[120])}
        self.assertEqual(objective(days,idx,{},C,120,60)["label"],"bull")
        C[125]=.8
        idx={k:C.copy() for k in idx}
        y=objective(days,idx,{},C,120,60)
        self.assertEqual(y["label"],"bull")
        self.assertTrue(y["risk"])
    def test_horizon_missing(self):
        self.assertIsNone(objective(["2024-01-01"],{}, {},[1.],0,60))
    def test_risk_denominator(self):
        p={"state":"bull","high":True,"new_high":True}
        result=metrics([(p,{"label":"bull","risk":True}),(p,{"label":"bull","risk":False}),(p,None)])
        self.assertEqual(result["dangerous_high_cap"],{"n":1,"N":2,"pct":50.0})
if __name__=="__main__":unittest.main()
