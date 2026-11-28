import unittest
from datetime import datetime,timedelta
from technical.model_e0 import *
class E0Test(unittest.TestCase):
    def test_draw(self):
        g={"a":[str(i) for i in range(20)],"b":["b"],"c":["c"]}
        x=draw(g,5,"k");self.assertEqual(sum(map(len,x.values())),5);self.assertEqual(x,draw(dict(reversed(list(g.items()))),5,"k"));self.assertEqual(len(x["b"]),1)
        self.assertEqual(sum(map(len,draw(g,1,"k").values())),1)
        with self.assertRaises(ValueError):draw({"a":["x"],"b":["x"]},2,"k")
    def test_strata(self):
        u={"600001.SH":("20200101",None),"600002.SH":("20200101","20240101"),"600003.SH":("20250101",None),"300001.SZ":("20200101",None),"002475.SZ":("20200101",None)}
        ds={(datetime(2024,1,1)+timedelta(days=i)).strftime("%Y%m%d"):{"600001.SH":100} for i in range(20)}
        g=strata(u,"20240201",ds,"Q")
        self.assertEqual({k for v in g.values() for k in v},{"600001.SH","300001.SZ"})
        self.assertIn("ChiNext/missing",g)
    def test_calendar_gap(self):
        class API:
            def ask(self,*a,**k):return [{"cal_date":"20260101","is_open":0}]
        with self.assertRaises(ValueError):full_calendar(API(),"20260101","20260102")
    def test_common_calendar_and_mismatch(self):
        class API:
            def __init__(self,mismatch=False):self.mismatch=mismatch
            def ask(self,name,p,fields):
                return [{"cal_date":"20260101","is_open":0},{"cal_date":"20260102","is_open":0 if self.mismatch and p["exchange"]=="SZSE" else 1},{"cal_date":"20260103","is_open":1}]
        self.assertEqual(common_calendar(API(),"20260101","20260103"),["20260102","20260103"])
        with self.assertRaises(ValueError):common_calendar(API(True),"20260101","20260103")
    def test_feature_window_before_calendar(self):
        class Q:dates=["20100101","20230103"]
        # Synthetic monthly counts with first required bar older than calendar.
        bs=[{"date":"20100101","complete":True} for _ in range(60)]+[{"date":"20230103","complete":True}]
        v={"asof":"20230103","last_major":None,"groups":{"day":{"bars":[]},"week":{"bars":[]},"month":{"bars":bs}}}
        x=feature_calendar_diagnostics(Q(),v,["20120104","20230103"])
        self.assertEqual(x["month"]["state"],"calendar_not_covered")
    def test_cache_full_parity(self):
        ds=[(datetime(2024,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(90) if (datetime(2024,1,1)+timedelta(days=i)).weekday()<5]
        code="600001.SH";raw=[dict(ts_code=code,trade_date=d,open=10,high=11,low=9,close=10,vol=100,amount=100,pre_close=10,pct_chg=0) for d in ds]
        fs=[dict(ts_code=code,trade_date=d,adj_factor=1) for d in ds]
        q=QualityHistory(raw,fs,code,ds[-1]);ch=CachedHistory(q,ds,2)
        for d in ds[-5:]:self.assertEqual(q.view(d,ds),ch.view(d,ds))
        self.assertEqual(len(ch.cache),2);ch.view(ds[-1],ds);self.assertEqual(ch.hits,1)
        with self.assertRaises(ValueError):ch.view(ds[-1],list(ds))
    def test_delist_no_fake_last(self):
        class API:
            def ask(self,name,params,fields):
                d="20240102";k="600001.SH"
                if name=="daily":return [dict(ts_code=k,trade_date=d,open=10,high=11,low=9,close=10,vol=100,amount=100,pre_close=10,pct_chg=0)]
                return [dict(ts_code=k,trade_date=d,adj_factor=1)]
        q,m=historical_history(API(),"600001.SH",("20240101","20240103"),"20240110")
        self.assertEqual(q.asof,"20240102");self.assertEqual(m["requested_end"],"20240103")
if __name__=="__main__":unittest.main()
