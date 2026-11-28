import unittest
from technical.e1_scope_candidates import *
from technical.e1_scope_study import add_stats
from collections import Counter
def fixture(ds,bad=None):
    raw=[{"ts_code":"600615.SH","trade_date":d,"open":10,"high":10,"low":10,"close":10,"vol":10,"amount":None if d==bad else 10,"pre_close":10,"pct_chg":0} for d in ds]
    fs=[{"ts_code":"600615.SH","trade_date":d,"adj_factor":1} for d in ds]
    return raw,fs
class ScopeTest(unittest.TestCase):
    def test_dw_weights_and_missing(self):
        v={"groups":{f:{"feature_ready":True} for f in ("day","week","month")}}
        a={"cycles":{"day":{"T":100,"M":0},"week":{"T":-100,"M":0}},"horizons":{h:{"V":{"V":0},"R":{"R":0}} for h in DW}}
        ok,s=dw_scores(a,v);self.assertTrue(ok);self.assertAlmostEqual(s["short"],.55*100*40/90);self.assertAlmostEqual(s["medium"],-.55*100/3)
        a["cycles"]["week"]["T"]=None;self.assertIsNone(dw_scores(a,v)[1]["short"])
    def test_restart_old_bad_and_future(self):
        ds=["20220131","20220201","20220202","20220301","20220302","20220401"];r,f=fixture(ds,"20220201")
        bad=invalid_dates(r,f,"600615.SH");self.assertEqual(bad,["20220201"])
        q,m=h_history(r,f,"600615.SH","20220131",ds,bad);self.assertEqual(q.dates,["20220131"])
        self.assertIsNone(h_history(r,f,"600615.SH","20220202",ds,bad)[0])
        q,m=h_history(r,f,"600615.SH","20220302",ds,bad);self.assertEqual(m["start"],"20220301")
        qp,mp=h_history(r[:5],f[:5],"600615.SH","20220302",ds,invalid_dates(r[:5],f[:5],"600615.SH"))
        self.assertEqual(q.view("20220302",ds),qp.view("20220302",ds))
        self.assertEqual(q.view("20220302",ds),QualityHistory(r[3:5],f[3:5],"600615.SH","20220302").view("20220302",ds))
        self.assertTrue(all(x!="complete" for x in restart_checks(q,q.view("20220302",ds),ds,("day","week","month")).values()))
    def test_invalid_identity_and_duplicates(self):
        r,f=fixture(["20230103","20230104"])
        self.assertEqual(invalid_dates(r+[r[1]],f,"600615.SH"),["20230104"])
        self.assertEqual(invalid_dates(r,f+[f[1]],"600615.SH"),["20230104"])
        r[0]["ts_code"]="000001.SZ";self.assertIsNone(invalid_dates(r,f,"600615.SH"))
    def test_bad_label_window(self):
        ds=["20230103","20230104","20230105"];r,f=fixture(ds);q=QualityHistory(r,f,"600615.SH",ds[-1])
        self.assertFalse(label_only(q,ds[0],1,ds,[ds[1]])["eligible"])
        self.assertEqual(label_only(q,ds[0],1,ds,[ds[2]]),q.label_admission(ds[0],1,ds))
    def test_repeated_anomaly_and_verified_calendar(self):
        cal=["20120104","20120201","20230103","20230201","20230301"]
        self.assertEqual(segment_bounds(["19931223","20230103"],"20230103",cal),("20230103","20230201",None))
        self.assertEqual(segment_bounds(["19931223","20230103"],"20120201",cal),("19931223","20120104","20230103"))
    def test_missing_and_all_blocked(self):
        c=Counter();add_stats(c,{k:blank() for k in ARMS});self.assertEqual(c["planned"],1);self.assertEqual(c["DW.scored.neither"],1)
