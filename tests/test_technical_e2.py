import unittest,os
from unittest.mock import patch
from technical.e2_evidence import *
from technical.e2_a1 import private_guard
from technical.e1_scope_candidates import invalid_dates,h_history,restart_checks
from technical.model_e0 import QualityHistory
CODE="600615.SH"
DS=["20230103","20230104","20230105","20230106","20230109","20230110","20230111","20230112"]
def fixture():
    raw=[{"ts_code":CODE,"trade_date":d,"open":10,"high":11,"low":9,"close":10,"vol":100,"amount":100,"pre_close":10,"pct_chg":0} for d in DS]
    fs=[{"ts_code":CODE,"trade_date":d,"adj_factor":1} for d in DS]
    return raw,fs
def check(r,f,meta=None):
    return verify_window(r,f,CODE,DS[1],5,DS,meta or {"purged":False,"label_end_by_horizon":{"5":DS[6]}})
class EvidenceTests(unittest.TestCase):
    def test_outcome_path(self):
        r,f=fixture();w,s=check(r,f);self.assertEqual(s,"ok");y=outcome(w)
        self.assertAlmostEqual(y["r"],0);self.assertAlmostEqual(y["mae"],-.1);self.assertAlmostEqual(y["mfe"],.1)
    def test_missing_and_duplicate(self):
        r,f=fixture();self.assertIsNone(check(r[:3]+r[4:],f)[0]);self.assertIsNone(check(r+[r[3]],f)[0])
    def test_future_boundary(self):
        r,f=fixture();r[-1]["amount"]=None
        self.assertEqual(check(r,f)[1],"ok");r[-2]["amount"]=None;self.assertIsNone(check(r,f)[0])
    def test_major_factor_event(self):
        r,f=fixture();f[2]["adj_factor"]=2;self.assertEqual(check(r,f)[1],"major_continuity")
        r,f=fixture();f[1]["adj_factor"]=2;self.assertEqual(check(r,f)[1],"major_continuity")
    def test_purge_and_endpoint(self):
        r,f=fixture();self.assertIsNone(check(r,f,{"purged":True,"label_end_by_horizon":{"5":DS[6]}})[0])
        self.assertIsNone(check(r,f,{"purged":False,"label_end_by_horizon":{"5":DS[5]}})[0])
    def test_invalid_identity_or_date(self):
        r,f=fixture();r[3]["ts_code"]="wrong";self.assertIsNone(check(r,f)[0]);r[3]["trade_date"]="bad";self.assertIsNone(check(r,f)[0])
    def test_ic_and_ties(self):
        self.assertAlmostEqual(ic(list(range(10)),list(range(10))),1)
        self.assertAlmostEqual(ic(list(range(10)),list(reversed(range(10)))),-1)
        self.assertIsNone(ic([1]*10,list(range(10))));self.assertIsNone(ic([1,2],[2,1]))
        self.assertEqual(ranks([1,1,2]),[1.5,1.5,3])
    def test_benchmark_missing_no_renormalize(self):
        codes=["000300.SH","000905.SH","000852.SH"];ix={k:{d:100 for d in DS} for k in codes}
        self.assertAlmostEqual(benchmark(ix,codes,DS),1);del ix[codes[0]][DS[-1]];self.assertIsNone(benchmark(ix,codes,DS))
    def test_metrics_and_sparse(self):
        rows=[{"date":DS[0],"score":-30 if i<5 else 30,"r":-.1 if i<5 else .1,"mae":-.1 if i<5 else 0.,"mfe":.1,"dd":-.1,"risk":None,"regime":"mixed","excess":None} for i in range(10)]
        v=metrics(rows,5,"DW");self.assertAlmostEqual(v["equal_date"]["spread"]["mean"],.2);self.assertEqual(v["balanced_accuracy"],1);self.assertEqual(v["downside_n"],5)
        self.assertIsNone(metrics([],5,"DW")["balanced_accuracy"])
    def test_private_guard(self):
        with patch.dict(os.environ,{"E2_PRIVATE_RESEARCH_AUTHORIZED":"1","GITHUB_ACTIONS":"true","E2_REPOSITORY_PRIVATE":"false"}):
            with self.assertRaises(RuntimeError):private_guard()
        with patch.dict(os.environ,{"E2_PRIVATE_RESEARCH_AUTHORIZED":"0"}):
            with self.assertRaises(RuntimeError):private_guard()
