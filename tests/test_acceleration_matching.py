import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"acceleration"))
from matching import *
class MatchingTest(unittest.TestCase):
    def x(self,k,g,s=None,i="A",cap=100,pe=20):return {"code":k,"growth":g,"signal":s,"industry":i,"cap":cap,"pe":pe}
    def test_assignment(self):
        self.assertEqual(assignment([[1,2,10000,10000],[1,1e6,10000,10000]]),[(0,1),(1,0)])
    def test_match(self):
        rows=[self.x("a",.4,"early"),self.x("b",.42,"sustained"),self.x("c",.41),self.x("d",.39,i="B"),self.x("e",.39,cap=500)]
        p,r=match(rows,"union")
        self.assertEqual(len(p),1);self.assertEqual(p[0][1]["code"],"c");self.assertEqual(r["competition_unmatched"],1)
        self.assertEqual(len(match(rows,"union",False)[0]),2)
    def test_distance(self):
        a=self.x("a",.4,"early")
        self.assertIsNone(distance(a,self.x("b",.8),True))
        self.assertIsNone(distance(a,self.x("b",.4,pe=None),True))
        self.assertIsNone(distance(a,self.x("b",.4,i="B"),True))
        self.assertIsNotNone(distance(a,self.x("b",.4,cap=200,pe=40),True))
    def test_industry(self):
        x={"ts_code":"a","l1_code":"A","in_date":"20220101","out_date":"20230101","is_new":"N"}
        y={**x,"l1_code":"B","in_date":"20230101","out_date":None,"is_new":"Y"}
        self.assertEqual(industry_at([x,y],"20221231"),{"a":"A"})
        self.assertEqual(industry_at([x,y],"20230101"),{"a":"B"})
        self.assertEqual(industry_at([x,{**x,"l1_code":"C"}],"20221231"),{})
    def test_pairs(self):
        p=[(self.x("a"+str(i),.4,"early"),self.x("b"+str(i),.3)) for i in range(5)]
        v={x["code"]:.5 for a,b in p for x in (a,b)}
        z=paired(p,v,"growth");self.assertTrue(z["coverage_pass"]);self.assertAlmostEqual(z["median_change_gap"],-.1)
        del v["b0"];self.assertFalse(paired(p,v,"growth")["coverage_pass"])
    def test_drawdown(self):
        self.assertAlmostEqual(sampled_drawdown([100,120,90,110]),.25)
        self.assertIsNone(sampled_drawdown([100,None,110]))
if __name__=="__main__":unittest.main()
