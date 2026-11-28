import unittest
from collections import Counter
from technical.e1_q1_audit import count_row,population_vol
class AuditTest(unittest.TestCase):
    def test_missing_is_in_denominator(self):
        c=Counter();count_row(c,None,"delisted_or_after_exit")
        self.assertEqual(dict(c),{"planned":1,"not_observed":1,"delisted_or_after_exit":1})
    def test_joint_not_marginal(self):
        r={"view":{"combined_feature_ready":True,"last_major":None},"A":{"composite_ready":True},
           "B":{"market_industry_context":{k:True for k in ("market_ready","breadth_ready","liquidity_ready","industry_ready")}},
           "C":{},"coverage":{"day":{"state":"complete"},"month":{"state":"gaps"}},"admission":{"5":{"eligible":True,"reason":"clean"}}}
        c=Counter();count_row(c,r)
        self.assertEqual(c["scored_label_5"],1);self.assertEqual(c["strict_scored_label_5"],0)
