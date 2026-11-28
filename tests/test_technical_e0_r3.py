import unittest,tempfile,json
from technical.e0_r3_store import Ledger
from technical.e0_r3_index import CalendarIndex,indexed
from technical import model_c_r1 as C
class R3Test(unittest.TestCase):
    def test_calendar_indexes(self):
        cal=["20230103","20230104","20230105","20230106","20230109","20230110","20230113","20230116"]
        idx=CalendarIndex(cal);b=[{"date":d} for d in cal if d!="20230105"]
        w=[{"date":"20230106","complete":True,"sessions":4},{"date":"20230113","complete":True,"sessions":3}]
        v={"groups":{"week":{"bars":w}}}
        old=C.contiguous_tail(b,"day",cal,"20230116");oldw=C.completed_bars(v,"week",cal)
        from technical.e0_r3_index import completed_bars
        with indexed(idx):
            self.assertEqual(C.contiguous_tail(b,"day",cal,"20230116"),old)
            self.assertEqual(completed_bars(v,"week",cal),oldw)
        self.assertEqual(C.contiguous_tail(b,"day",cal,"20230116"),old)
    def test_checkpoint_resume_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            a=Ledger(d,"version");result={"counts":{"planned":2,"computed":1,"not_observed":1},"output_digest":"x"}
            a.write("600001.SH","source",result)
            self.assertEqual(Ledger(d,"version").read("600001.SH","source"),result)
            self.assertIsNone(Ledger(d,"other").read("600001.SH","source"))
            self.assertIsNone(a.read("600001.SH","other"))
            p=a.file("600001.SH");x=json.loads(p.read_text());x["result"]["output_digest"]="corrupt";p.write_text(json.dumps(x))
            self.assertIsNone(a.read("600001.SH","source"))
    def test_zones_exact(self):
        cal=["20230103","20230104","20230105","20230106","20230109","20230110","20230111","20230112","20230113"]
        b=[{"date":d,"close":10 if i not in (5,6) else 8} for i,d in enumerate(cal)]
        e=[{"price":9,"side":"support","frequency":"day","formation":cal[0],"confirmed":cal[2],"kind":"rejection"},
           {"price":11,"side":"resistance","frequency":"day","formation":cal[1],"confirmed":cal[3],"kind":"rejection"}]
        old=C.zones_for(e,b,1,cal,("day",))
        with indexed(CalendarIndex(cal)):self.assertEqual(C.zones_for(e,b,1,cal,("day",)),old)
