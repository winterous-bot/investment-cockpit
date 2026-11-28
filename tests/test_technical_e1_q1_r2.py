import unittest,tempfile
from unittest.mock import patch
from collections import Counter
from technical import e1_q1_audit as audit
from technical.e1_q1_r1 import AuditLedger
from technical.e1_q1_r2 import validate_stock,validate_panels,stock_event,checkpoint_hit,validate_counts,expected_panels
from technical.model_e0 import digest
DATES=["20230106","20230113"];WEEKLY=DATES;CODE="600615.SH"
def blocked(daily=False,state="data_quality"):
    diag={"code":CODE,"state":state,"first_invalid":"19931223","observed_dates":DATES}
    ctx=(DATES,{}, {},{d:{} for d in DATES},{d:"unknown" for d in DATES},{})
    with patch.object(audit,"CTX",ctx):
        return audit.isolated_worker((None,[],DATES,WEEKLY,"main/low",daily,False,("19930101",None),diag))
class BoundaryTests(unittest.TestCase):
    def test_zero_stock_end_to_end(self):
        r=blocked()
        validate_stock(r,DATES,WEEKLY,False,"data_quality","19931223")
        self.assertEqual(stock_event(CODE,r,20,240)["computed"],0)
        self.assertEqual(stock_event(CODE,r,20,240)["data_quality_blocked"],2)
        self.assertEqual(r["counts"]["planned"],2)
    def test_all_blocked_daily_overlap(self):
        r=blocked(True)
        validate_stock(r,DATES,WEEKLY,True,"data_quality","19931223")
        self.assertEqual(r["panels"]["overlap"]["data_quality_blocked"],2)
    def test_all_source_unavailable(self):
        r=blocked(True,"source_unavailable")
        validate_stock(r,DATES,WEEKLY,True,"source_unavailable","19931223")
        self.assertEqual(stock_event(CODE,r,1,240)["source_unavailable"],2)
    def test_empty_collections(self):
        validate_panels({}, {}, dict.fromkeys(("core","daily","overlap","unique"),0))
        validate_counts({},0)
    def test_all_missing(self):
        c=Counter()
        for d in DATES:audit.count_row(c,None,"missing_or_suspended_observation")
        validate_counts(dict(c),2)
        self.assertEqual(stock_event(CODE,{"counts":dict(c)},1,240)["computed"],0)
    def test_legacy_zero_stock_restore(self):
        r=blocked()
        with tempfile.TemporaryDirectory() as d:
            l=AuditLedger(d,"old");l.write(CODE,"source",r)
            self.assertEqual(checkpoint_hit(l,CODE,"source",DATES,WEEKLY,False,"data_quality","19931223"),r)
            self.assertIsNone(checkpoint_hit(l,CODE,"changed",DATES,WEEKLY,False,"data_quality","19931223"))
            self.assertIsNone(checkpoint_hit(l,CODE,"source",DATES,WEEKLY,False,"data_quality","19931224"))
            self.assertIsNone(checkpoint_hit(l,CODE,"source",DATES,WEEKLY,False,"source_unavailable","19931223"))
            self.assertIsNone(checkpoint_hit(AuditLedger(d,"other"),CODE,"source",DATES,WEEKLY,False,"data_quality","19931223"))
    def test_reject_bad_dimension(self):
        r=blocked()
        r["dimensions"].pop(next(iter(r["dimensions"])))
        with self.assertRaises(ValueError):validate_stock(r,DATES,WEEKLY,False,"data_quality","19931223")
    def test_reject_negative_and_double_count(self):
        for c in ({"planned":1,"computed":-1,"not_observed":2},{"planned":1,"computed":1,"data_quality_blocked":1},{"planned":1,"computed":True}):
            with self.assertRaises(ValueError):validate_counts(c,1)
