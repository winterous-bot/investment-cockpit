import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"radar"))
from model import classify,metrics,cross_section,ret,summarize,mdd
class RadarTests(unittest.TestCase):
    def base(self):return dict(rs5=.03,rs20=.08,r5=.05,ma20_gap=.05,rank_pct=.10,rank_move=.30,attention=1.3,persistence=3)
    def test_start(self):self.assertEqual(classify(self.base()),"启动")
    def test_overheat_priority(self):self.assertEqual(classify({**self.base(),"r5":.13}),"过热")
    def test_decline(self):self.assertEqual(classify({**self.base(),"rs5":-.01,"rank_move":-.2,"attention":.9}),"退潮")
    def test_main(self):self.assertEqual(classify({**self.base(),"rank_move":.05}),"主升")
    def test_missing(self):
        a=[1.]*35;a[25]=None
        self.assertIsNone(ret(a,30,5))
        self.assertIsNone(metrics(a,[.02]*35,[1.]*35,30))
    def test_attention_prior_no_overlap(self):
        a=[1.+i*.01 for i in range(35)];b=[1.]*35;s=[.01]*30+[.02]*5
        self.assertAlmostEqual(metrics(a,s,b,34)["attention"],2.)
    def test_ranks_missing(self):
        x=cross_section({"a":[1.]*35,"b":[1.]*34+[None]}, {"a":[.01]*35,"b":[.01]*35},[1.]*35,34,[{}]*34)
        self.assertEqual(x,{})
    def test_drawdown(self):self.assertAlmostEqual(mdd([100,120,90,110]),.25)
if __name__=="__main__":unittest.main()
