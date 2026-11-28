import unittest
from datetime import date,timedelta
from technical.model_a import (vote,trend_score,momentum_score,trend_state,direction_state,weighted,
    relative_component,volume_component,cluster_levels,alignment,medium_state,analyze,cycle,reversal,location,INDEX_WEIGHTS)
from technical.quality import QualityHistory
def history():
    days=[(date(2010,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(4500) if (date(2010,1,1)+timedelta(days=i)).weekday()<5]
    raw=[];factors=[]
    for i,d in enumerate(days[:-25]):
        # deterministic trending sample, no rounded pre_close discrepancies.
        c=100+i*.1;prev=100+(i-1)*.1 if i else c
        raw.append(dict(ts_code="X",trade_date=d,open=c,high=c+1,low=c-1,close=c,vol=100,amount=100,pre_close=prev,pct_chg=100*(c/prev-1)))
        factors.append(dict(ts_code="X",trade_date=d,adj_factor=1))
    return days,raw,factors
class ModelATest(unittest.TestCase):
    def test_votes_and_boundaries(self):
        self.assertEqual([vote(v,.0025) for v in (-.0026,-.0025,0,.0025,.0026)],[-1,0,0,0,1])
        self.assertIsNone(vote(None,1))
        self.assertEqual([trend_state(v) for v in (-50,-49.9,49.9,50)],["bearish","range","range","bullish"])
        self.assertEqual([direction_state(v) for v in (-50,-20,0,20,50)],["strong_negative","negative","mixed","positive","strong_positive"])
    def test_hand_scores(self):
        c={"close":110,"ma5":109,"ma10":105,"ma20":100}
        self.assertEqual(trend_score(c,99),100)
        self.assertEqual(trend_score(c,100),75)
        self.assertEqual(trend_score(dict(c,close=90),99),40)
        self.assertIsNone(trend_score(c,None))
        self.assertEqual(momentum_score({"close":100,"macd":.2,"rsi12":56},.1),100)
        self.assertEqual(momentum_score({"close":100,"macd":-.2,"rsi12":44},-.1),-100)
        self.assertEqual(momentum_score({"close":100,"macd":.1,"rsi12":55},.05),0)
        self.assertEqual(weighted([100,0,-100],[.65,.25,.10]),55)
        self.assertIsNone(weighted([100,None],[.5,.5]))
    def test_relative_calendar_and_coverage(self):
        ds=[str(i) for i in range(100,161)]
        s=[{"date":d,"close":100+i} for i,d in enumerate(ds)]
        b=[{"date":d,"close":100} for d in ds]
        ix={k:b for k in INDEX_WEIGHTS}
        self.assertEqual(relative_component(s,ix,ds,ds[-1],(20,60))["R"],100)
        ix.pop("932000.CSI")
        self.assertEqual(relative_component(s,ix,ds,ds[-1],(20,60))["coverage"],.8)
        ix.pop("000300.SH")
        self.assertIsNone(relative_component(s,ix,ds,ds[-1],(20,60))["R"])
        self.assertIsNone(relative_component(s[:-2]+s[-1:],ix,ds,ds[-1],(20,60))["R"])
    def test_volume_and_cluster(self):
        bars=[{"close":100,"high":101,"low":99,"vol":100} for _ in range(20)]+[{"close":103,"high":104,"low":102,"vol":150}]
        v={"last_major":None,"groups":{"day":{"bars":bars}}}
        self.assertEqual(volume_component(v,"day")["V"],100)
        bars[-1]["vol"]=74;self.assertEqual(volume_component(v,"day")["V"],0)
        v["groups"]["week"]={"bars":[dict(b,complete=True) for b in bars]};v["groups"]["week"]["bars"][-1]["complete"]=False
        self.assertIsNone(volume_component(v,"week")["V"])
        a=cluster_levels([(10,"a"),(10.4,"b"),(10.8,"c")],1)
        self.assertEqual(len(a),2);self.assertEqual(a[0]["sources"],["a","b"])
    def test_conflicts(self):
        cy={f:{"trend":v} for f,v in zip(("day","week","month"),("bullish","bearish","bearish"))}
        self.assertEqual(alignment(cy),"rebound_in_downtrend")
        self.assertEqual(medium_state(cy),"bearish")
        cy["month"]["trend"]="bullish";self.assertEqual(medium_state(cy),"conflicting_or_range")
    def test_prefix_and_missing_benchmarks(self):
        ds,raw,fs=history();last=raw[-1]["trade_date"];q=QualityHistory(raw,fs,"X",last)
        ix={k:[{"date":r["trade_date"],"close":100} for r in raw] for k in INDEX_WEIGHTS}
        a=analyze(q,last,ds,ix)
        self.assertTrue(a["composite_ready"]);self.assertIsNone(a["probability"])
        self.assertEqual(a["action"],"evidence_insufficient_context")
        d=raw[-8]["trade_date"];ix2={k:[r for r in v if r["date"]<=d] for k,v in ix.items()}
        b=analyze(q,d,ds,ix2)
        self.assertEqual(b,analyze(QualityHistory(raw[:-7],fs[:-7],"X",d),d,ds,ix2))
        self.assertFalse(analyze(q,d,ds,ix)["composite_ready"])
        self.assertFalse(analyze(q,last,ds,{})["composite_ready"])
    def test_major_guard_and_missing_history(self):
        ds,raw,fs=history()
        raw=raw[-80:];fs=fs[-80:];d=raw[-1]["trade_date"]
        q=QualityHistory(raw,fs,"X",d)
        self.assertFalse(analyze(q,d,ds,{})["composite_ready"])
        raw[-2]["pre_close"]=raw[-2]["close"]*2;raw[-2]["pct_chg"]=-50
        q=QualityHistory(raw,fs,"X",d)
        r=analyze(q,d,ds,{})
        self.assertEqual(r["quality"]["last_major"],raw[-2]["trade_date"])
        self.assertIsNone(r["cycles"]["day"]["M"]);self.assertIsNone(r["horizons"]["short"]["D"])
        self.assertIsNone(r["location"]["risk_veto"])
    def test_risk_guard(self):
        ds,raw,fs=history();d=raw[-1]["trade_date"];v=QualityHistory(raw,fs,"X",d).view(d,ds)
        l=location(v);self.assertTrue(l["risk_veto"]) # trending all-time high, missing resistance
        self.assertTrue(l["flags"]["missing_level"])
        self.assertIsNone(l["reward_risk"])
if __name__=="__main__":unittest.main()
