import importlib.util,unittest,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
spec=importlib.util.spec_from_file_location("research_plan",Path(__file__).resolve().parents[1]/"scripts/research-plan.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PlanTest(unittest.TestCase):
    def test_time_and_holiday(self):
        rows=[{"cal_date":"20261125","is_open":1},{"cal_date":"20261126","is_open":1},{"cal_date":"20261127","is_open":0}]
        def p(s):return m.plan(datetime.fromisoformat(s).replace(tzinfo=ZoneInfo("Asia/Shanghai")),rows)
        self.assertEqual(p("2026-11-26T18:14")["target"],"20261125")
        self.assertEqual(p("2026-11-26T18:15")["due"],{"radar":True,"growth":False,"watchlist":False})
        self.assertEqual(p("2026-11-26T18:45")["due"],{"radar":True,"growth":True,"watchlist":False})
        self.assertTrue(all(p("2026-11-26T21:30")["due"].values()))
        self.assertEqual(p("2026-11-27T07:10")["target"],"20261126")
        self.assertTrue(all(p("2026-11-27T23:10")["due"].values()))
        with self.assertRaises(RuntimeError):m.plan(datetime(2026,11,26,23),[])
