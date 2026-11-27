import unittest
from technical.indicators import normalize,aggregate,indicators,risk_features,relative_strength,ema,rsi
from technical.data import chunks
def bar(d,c,code="000001.SZ",vol=10):
    return dict(ts_code=code,trade_date=d,open=c,high=c+1,low=c-1,close=c,vol=vol,amount=100)
def fac(d,f):return dict(ts_code="000001.SZ",trade_date=d,adj_factor=f)
class FoundationTest(unittest.TestCase):
    def test_adjustment_aggregation_and_cutoff(self):
        rows=[bar("20261127",20),bar("20261126",19),bar("20261125",36)]
        factors=[fac("20261125",1),fac("20261126",2),fac("20261127",2)]
        x=normalize(rows,factors,"000001.SZ","20261127")
        self.assertEqual([r["close"] for r in x],[18,19,20]);self.assertEqual(x[-1]["close"],20)
        self.assertEqual([r["vol"] for r in x],[10,10,10])
        cal=["20261125","20261126","20261127","20261130"]
        w=aggregate(x,"week","20261127",cal)[0];m=aggregate(x,"month","20261127",cal)[0]
        self.assertEqual(w["vol"],30);self.assertEqual(w["open"],18);self.assertEqual(w["high"],21);self.assertEqual(w["low"],17.5)
        self.assertTrue(w["complete"]);self.assertFalse(m["complete"])
        for rs,fs in [(rows+[bar("20261130",22)],factors),(rows,factors[:-1]),(rows+[rows[0]],factors),(rows[1:],factors)]:
            with self.assertRaises(ValueError):normalize(rs,fs,"000001.SZ","20261127")
    def test_indicators(self):
        x=[dict(close=float(i),high=i+1,low=i-1,vol=100,amount=1) for i in range(1,261)]
        m=indicators(x,"day")
        self.assertEqual(m["ma5"],258);self.assertEqual(m["ma250"],135.5);self.assertEqual(m["rsi6"],100)
        self.assertAlmostEqual(m["dif"],7,places=5);self.assertAlmostEqual(m["dea"],7,places=5)
        self.assertAlmostEqual(m["macd"],0,places=5);self.assertAlmostEqual(m["boll_mid"],250.5)
        self.assertAlmostEqual(m["boll_upper"],250.5+2*(33.25**.5))
        self.assertEqual(m["vol_ma5"],100);self.assertEqual(m["vol_ma10"],100)
        self.assertIsNone(indicators(x[:10],"day")["ma250"])
        self.assertIsNone(indicators(x[:10],"day")["dif"])
        self.assertIsNone(rsi([10]*30,6));self.assertEqual(rsi(list(range(30,0,-1)),6),0)
        self.assertEqual(ema([1,3],3),[1,2])
        self.assertAlmostEqual(risk_features(x)["atr14"],2)
    def test_rs_and_chunks(self):
        s=[{"date":str(i),"close":p} for i,p in enumerate([10,11,12])]
        b=[{"date":str(i),"close":p} for i,p in enumerate([10,10,11])]
        self.assertAlmostEqual(relative_strength(s,b,2),(1.2/1.1-1)*100)
        self.assertIsNone(relative_strength(s,b[:-1],2))
        self.assertEqual(list(chunks("20200101","20261127")),[("20200101","20221231"),("20230101","20251231"),("20260101","20261127")])
if __name__=="__main__":unittest.main()
