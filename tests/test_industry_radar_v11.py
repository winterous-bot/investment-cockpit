import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"radar"))
from model_v11 import flags,stock_metrics,stock_lists,timeline
class Radar11Tests(unittest.TestCase):
    def test_early(self):
        x=dict(attention=1.4,r5=.02,rs5=.01,rank_move=.12,ma20_gap=.02)
        self.assertIn("量价前兆",flags(x))
        self.assertNotIn("量价前兆",flags({**x,"r5":-.01}))
        self.assertIn("放量下跌",flags({**x,"r5":-.01}))
        self.assertNotIn("量价前兆",flags({**x,"rs5":-.01}))
    def test_missing(self):
        self.assertEqual(flags(dict(attention=1.5)),[])
        self.assertIsNone(stock_metrics([(1,1)]*24+[None],.02,.1))
    def test_amount_nonoverlap(self):
        x=stock_metrics([(0,10)]*20+[(1,20)]*5,.1,.2)
        self.assertAlmostEqual(x["amount_ratio"],2.)
        self.assertAlmostEqual(x["r5"],1.01**5-1)
    def test_paired_breadth(self):
        a=[dict(code="a",r5=.02,prev5=-.01,r20=.1,amount_ratio=1.3),dict(code="b",r5=-.01,prev5=-.02,r20=.1,amount_ratio=2)]
        x=stock_lists(a,.05,.12)
        self.assertEqual(x["breadth_change"],.5)
        self.assertEqual([v["code"] for v in x["laggard_watch"]],["a"])
        self.assertEqual(stock_lists(a,-.05,.12)["laggard_watch"],[])
    def test_timeline_missing(self):
        a=timeline([{},{"a":{"rank":1,"stage":"主升"}}],["20261124","20261125"],"a",1)
        self.assertEqual(a[0]["stage"],"证据不足")
        self.assertEqual(a[1]["rank"],1)
if __name__=="__main__":unittest.main()
