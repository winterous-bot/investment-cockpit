import unittest,tempfile
from technical.e1_q1_r1 import diagnosis,audited,AuditLedger,legacy_hit
from technical.e0_r3_store import Ledger
class R1Test(unittest.TestCase):
    def test_null_amount_is_not_repaired(self):
        k="600460.SH";rows=[{"ts_code":k,"trade_date":d,"open":10,"high":10,"low":10,"close":10,"vol":10,"amount":a,"pre_close":10,"pct_chg":0} for d,a in (("20230103",1),("20230104",None))]
        f=[{"ts_code":k,"trade_date":r["trade_date"],"adj_factor":1} for r in rows]
        with self.assertRaises(TypeError):audited(rows,f,k)
        self.assertEqual(diagnosis(rows,f,k),[{"date":"20230104","reason":"TypeError","fields":["amount"]}])
        self.assertEqual(audited(rows[:1],f[:1],k).dates,["20230103"])
    def test_ledger_distinct_denominators(self):
        with tempfile.TemporaryDirectory() as d:
            l=AuditLedger(d,"i");r={"counts":{"planned":3,"computed":1,"not_observed":1,"data_quality_blocked":1}}
            l.write("600460.SH","s",r);self.assertEqual(l.read("600460.SH","s"),r);self.assertIsNone(l.read("600460.SH","wrong"))
            self.assertIsNone(Ledger(d,"i").read("600460.SH","s"))
