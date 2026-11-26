import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"acceleration"))
from matched_build import memberships
from matching import industry_at
class MembershipRepairTest(unittest.TestCase):
    class API:
        def __init__(self,empty=False):self.empty=empty;self.calls=[]
        def ask(self,ep,params,fields):
            self.calls.append((ep,params))
            if ep=="index_classify":return [{"index_code":str(801010+i)+".SI","level":"L1","is_pub":"1"} for i in range(31)]
            if self.empty or not params["l1_code"].endswith(".SI"):return []
            k=params["l1_code"];flag=params["is_new"]
            return [{"l1_code":k,"ts_code":k.split(".")[0]+".SZ","in_date":"20220101" if flag=="N" else "20240101","out_date":"20240101" if flag=="N" else None,"is_new":flag}]
    def test_full_code_and_historical_members(self):
        a=self.API();rows,health=memberships(a)
        self.assertEqual(len(rows),62);self.assertEqual(len(health),62)
        self.assertEqual(len(industry_at(rows,"20230630")),31)
        self.assertEqual(len(industry_at(rows,"20250630")),31)
        self.assertTrue(all(p["l1_code"].endswith(".SI") for ep,p in a.calls if ep=="index_member_all"))
    def test_empty_api_response_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"Missing current or historical"):memberships(self.API(empty=True))
if __name__=="__main__":unittest.main()
