import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"/"v2"))
from v2_model import classify_candidate,state_sequence,index_trend,summarize,CONFIRM,INDEX_WEIGHTS

class FrozenV2Tests(unittest.TestCase):
    def row(self,**overrides):
        x={"date":"2024-03-01","T":10,"B":.5,"P60":.5,"I60":.5,"A5":.5,
           "up_votes":0,"down_votes":0,"drawdown120":-.03,
           "prior_decline":False,"repair_count":0,"leaders":0,
           "benchmark":1.,"benchmark_return":0.}
        x.update(overrides)
        return x

    def test_five_mutually_exclusive_states(self):
        self.assertEqual(classify_candidate(self.row(T=67,B=.73,P60=.8,I60=.7,A5=.65,up_votes=3)),"bull")
        self.assertEqual(classify_candidate(self.row(T=-75,B=.16,P60=.2,I60=.1,A5=.2,down_votes=3)),"bear")
        self.assertEqual(classify_candidate(self.row(T=-5,B=.32,P60=.4,I60=.25,A5=.3,prior_decline=True,repair_count=2)),"bottoming")
        self.assertEqual(classify_candidate(self.row(T=20,B=.51,leaders=3)),"structural")
        self.assertEqual(classify_candidate(self.row()),"range")

    def test_bear_over_bottom_priority(self):
        x=self.row(T=-65,B=.2,P60=.2,I60=.2,A5=.2,down_votes=3,
                   prior_decline=True,repair_count=3)
        self.assertEqual(classify_candidate(x),"bear")

    def test_nulls_do_not_classify(self):
        self.assertEqual(classify_candidate(self.row(I60=None)),"unknown")
        self.assertEqual(classify_candidate(self.row(leaders=None,repair_count=None)),"range")
        self.assertEqual(classify_candidate(self.row(T=None)),"unknown")

    def test_confirmation_requires_consecutive_candidates(self):
        bull=self.row(T=75,B=.77,P60=.8,I60=.7,A5=.7,up_votes=3)
        rows=[{**bull,"date":f"2024-03-{i+1:02d}"} for i in range(4)]
        self.assertEqual(state_sequence(rows)[-1]["state"],"unknown")
        rows.append({**bull,"date":"2024-03-05"})
        self.assertEqual(state_sequence(rows)[-1]["state"],"bull")
        bear=self.row(T=-85,B=.11,P60=.1,I60=.1,A5=.1,down_votes=3)
        rows+= [{**bear,"date":f"2024-03-{i:02d}"} for i in range(6,9)]
        self.assertEqual(state_sequence(rows)[-2]["state"],"bull")
        self.assertEqual(state_sequence(rows)[-1]["state"],"bear")

    def test_missing_data_interrupts_confirmation(self):
        bull=self.row(T=75,B=.8,P60=.8,I60=.8,A5=.8,up_votes=3)
        xs=[bull]*4+[self.row(I60=None)]+[bull]*4
        self.assertEqual(state_sequence(xs)[-1]["state"],"unknown")

    def test_trend_trailing_only(self):
        a=[100+x*.1 for x in range(260)]
        before=index_trend(a[:250])
        modified=a[:250]+[100000]
        self.assertEqual(before,index_trend(modified[:250]))

    def test_cost_and_holdout_no_negative_future_leakage(self):
        r=[self.row(date=f"2024-01-{i+1:02d}",T=70,B=.8,P60=.8,I60=.8,A5=.8,up_votes=3,
                    benchmark_return=.01) for i in range(10)]
        xs=state_sequence(r)
        result=summarize(xs)
        self.assertEqual(result["n"],8)
        self.assertGreater(result["turnover"],0)
        self.assertLess(result["annual_return"],result["benchmark_annual"])
if __name__=="__main__":unittest.main()
