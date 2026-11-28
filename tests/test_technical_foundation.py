import unittest
from technical.indicators import normalize,aggregate,indicators,risk_features,relative_strength,ema,rsi,directions
from technical.data import chunks
from technical.signals import crossing,signal_snapshot
from technical.r2 import provider_periods,oracle
from technical.r21 import unit_report,pick_periods,continuity
from technical.quality import QualityHistory,classify,public_summary
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
        self.assertAlmostEqual(m["boll_upper"],250.5+2*((665/19)**.5))
        self.assertEqual(m["vol_ma5"],100);self.assertEqual(m["vol_ma10"],100)
        self.assertIsNone(indicators(x[:10],"day")["ma250"])
        self.assertIsNone(indicators(x[:10],"day")["dif"])
        self.assertIsNone(rsi([10]*30,6));self.assertEqual(rsi(list(range(30,0,-1)),6),0)
        self.assertEqual(ema([1,3],3),[1,2])
        self.assertAlmostEqual(risk_features(x)["atr14"],2)
    def test_sample_boll_and_directions(self):
        from math import sqrt
        x=[dict(close=float(i),vol=i) for i in range(1,41)]
        m=indicators(x,"day")
        center=sum(range(21,41))/20
        sd=sqrt(sum((i-center)**2 for i in range(21,41))/19)
        self.assertAlmostEqual(m["boll_upper"],center+2*sd)
        self.assertAlmostEqual(m["boll_lower"],center-2*sd)
        a=directions(x,"day")
        self.assertEqual(a["ma5"],1);self.assertEqual(a["vol_ma10"],1);self.assertEqual(a["rsi6"],0)
        self.assertIsNone(a["ma250"])
    def test_r2_provider_alignment(self):
        local={(2026,10):{"date":"20261030","complete":True},(2026,11):{"date":"20261127","complete":False}}
        def row(label,end,close=10):
            return dict(ts_code="000001.SZ",freq="month",trade_date=label,end_date=end,close=close,vol=100,close_hfq=20,close_qfq=10)
        remote=[row("20261031","20261029"),row("20261031","20261030"),row("20261031","20261030"),row("20261130","20261127")]
        p,r,d=provider_periods(remote,"000001.SZ","month","20261127",local)
        self.assertEqual(len(p),1);self.assertEqual(p[(2026,10)][0],"20261030");self.assertEqual((r,d),(1,1))
        with self.assertRaises(RuntimeError):provider_periods(remote+[row("20261031","20261030",11)],"000001.SZ","month","20261127",local)
    def test_r2_signals(self):
        self.assertEqual([crossing(-1,1),crossing(1,-1),crossing(0,0),crossing(None,1)],[1,-1,0,None])
        x=[dict(close=float(i),high=i+1,low=i-1,vol=100) for i in range(10,100)]
        x.append(dict(close=110,high=111,low=109,vol=100))
        r=signal_snapshot(x,"day")
        self.assertEqual(r["prior_high20"],100);self.assertEqual(r["breakout20"],1)
        x.append(dict(close=1,high=2,low=.5,vol=100))
        self.assertEqual(signal_snapshot(x,"day")["breakout20"],-1)
        self.assertEqual(signal_snapshot(x,"day"),oracle(x,"day"))
    def test_r21_units(self):
        p=[(10000,100,0),(20000,200,10)]
        r=unit_report(p,(1,100),1)
        self.assertEqual([(x["divisor"],x["scope"]) for x in r if x["passed"]==x["n"]==2],[(100,"regular")])
        p=[(11000,100,10),(22000,200,20)]
        r=unit_report(p,(1,100),1)
        self.assertEqual([(x["divisor"],x["scope"]) for x in r if x["passed"]==x["n"]==2],[(100,"including_afterhours")])
    def test_r21_snapshot_vintage(self):
        local={(2026,10):{"date":"20261030","complete":True},(2026,11):{"date":"20261127","complete":False}}
        def row(label,end):
            return dict(ts_code="000001.SZ",freq="month",trade_date=label,end_date=end,open=10,high=11,low=9,close=10,vol=100,amount=100,
                open_hfq=20,high_hfq=22,low_hfq=18,close_hfq=20,open_qfq=10,high_qfq=11,low_qfq=9,close_qfq=10)
        rows=[row("20261031","20261029"),row("20261031","20261127"),row("20261031","20261128"),row("20261130","20261127")]
        m,s,e=pick_periods(rows,"000001.SZ","month","20261127",local,True)
        self.assertEqual(m[(2026,10)][0],"20261127");self.assertEqual(len(m),1);self.assertEqual(s["rejected_invalid_cutoff"],2)
    def test_r21_exright_continuity(self):
        rows=[dict(bar("20261125",20),pre_close=20,pct_chg=0),dict(bar("20261126",10),pre_close=10,pct_chg=0),dict(bar("20261127",11),pre_close=10,pct_chg=10)]
        factors=[fac("20261125",1),fac("20261126",2),fac("20261127",2)]
        r=continuity(rows,factors,"000001.SZ","20261127")
        self.assertEqual(r["factor_change_pre_close_pass"],1);self.assertEqual(r["factor_change_return_pass"],1);self.assertEqual(r["ordinary_return_pass"],1)
        r=continuity(rows,[fac("20261125",1),fac("20261126",1.8),fac("20261127",1.8)],"000001.SZ","20261127")
        self.assertEqual(r["factor_change_failed_pairs"],1)
    def test_quality_classification(self):
        a={"close":20};b={"trade_date":"20261126","close":10,"pre_close":10,"pct_chg":0}
        self.assertIsNone(classify(a,b,1,2))
        self.assertEqual(classify(a,b,1,1.8)["severity"],"major")
        self.assertEqual(classify(a,{"trade_date":"20261126","close":10},1,2)["reason"],"missing_or_invalid_reference")
        a={"close":500.018};b={"trade_date":"20261126","close":500,"pre_close":500,"pct_chg":0}
        # Small price discrepancy, valid return comparison and relative bound.
        self.assertEqual(classify(a,b,1,1.000001)["severity"],"minor")
        self.assertEqual(classify(a,b,1,1)["severity"],"major")
    def test_quality_prefix_and_label_isolation(self):
        from datetime import date as dt,timedelta
        ds=[(dt(2026,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(180) if (dt(2026,1,1)+timedelta(days=i)).weekday()<5]
        rows=[];fs=[]
        for i,d in enumerate(ds):
            c=20 if i<70 else 10
            rows.append(dict(bar(d,c),pre_close=20 if i==70 else c,pct_chg=-50 if i==70 else 0))
            fs.append(fac(d,1 if i<70 else 2))
        q=QualityHistory(rows,fs,"000001.SZ",ds[-1])
        self.assertEqual([(e["date"],e["severity"]) for e in q.events],[(ds[70],"major")])
        self.assertIsNone(q.view(ds[69],ds)["last_major"])
        z=q.view(ds[70],ds);self.assertTrue(all(not x["bars"] for x in z["groups"].values()))
        self.assertFalse(z["combined_feature_ready"])
        z=q.view(ds[71],ds);self.assertEqual(z["groups"]["day"]["count"],1)
        self.assertEqual(q.label_admission(ds[69],1,ds)["reason"],"major_event_in_label_window")
        self.assertEqual(q.label_admission(ds[70],1,ds)["reason"],"major_event_in_label_window")
        self.assertTrue(q.label_admission(ds[71],5,ds)["eligible"])
        self.assertFalse(q.training_admission(ds[71],5,ds)["eligible"])
        self.assertEqual(q.label_admission(ds[-1],5,ds)["reason"],"future_not_available")
        z=q.view(ds[-1],ds);self.assertIsNone(z["groups"]["day"]["indicators"]["dif"])
        self.assertTrue(all(b["date"]>ds[70] for b in z["groups"]["day"]["bars"]))
        for fq in ("week","month"):
            from technical.indicators import period
            self.assertTrue(all(period(b["date"],fq)>period(ds[70],fq) for b in z["groups"][fq]["bars"]))
        # Remove one observed session; never silently extend horizon to next observed bar.
        q2=QualityHistory([r for i,r in enumerate(rows) if i!=90],fs,"000001.SZ",ds[-1])
        self.assertEqual(q2.label_admission(ds[89],2,ds)["reason"],"missing_or_suspended_session")
    def test_quality_recursive_recovery(self):
        from datetime import date as dt,timedelta
        # 13 years of weekday observations, with a severe early structural break.
        ds=[(dt(2000,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(4800) if (dt(2000,1,1)+timedelta(days=i)).weekday()<5]
        rows=[];fs=[]
        for i,d in enumerate(ds):
            c=20 if i<70 else 10
            rows.append(dict(bar(d,c),pre_close=20 if i==70 else c,pct_chg=-50 if i==70 else 0))
            fs.append(fac(d,1 if i<70 else 2))
        q=QualityHistory(rows,fs,"000001.SZ",ds[-1]);v=q.view(ds[-2],ds)
        self.assertTrue(v["combined_feature_ready"])
        self.assertTrue(q.training_admission(ds[-2],1,ds)["eligible"])
        self.assertFalse(q.training_admission(ds[-2],1,ds[-30:])["eligible"])
    def test_rs_and_chunks(self):
        s=[{"date":str(i),"close":p} for i,p in enumerate([10,11,12])]
        b=[{"date":str(i),"close":p} for i,p in enumerate([10,10,11])]
        self.assertAlmostEqual(relative_strength(s,b,2),(1.2/1.1-1)*100)
        self.assertIsNone(relative_strength(s,b[:-1],2))
        self.assertEqual(list(chunks("20200101","20261127")),[("20200101","20221231"),("20230101","20251231"),("20260101","20261127")])
if __name__=="__main__":unittest.main()
