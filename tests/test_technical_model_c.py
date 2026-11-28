import unittest
from datetime import date,timedelta
from technical.model_c import *
def bars(n=85):
    return [dict(date=(date(2025,1,1)+timedelta(days=i)).strftime("%Y%m%d"),open=100,close=100,high=101,low=99,vol=100,amount=100) for i in range(n)]
def put(b,i,c,h,l,vol):
    b[i].update(open=c,close=c,high=h,low=l,vol=vol)
class ModelCTest(unittest.TestCase):
    def test_causal_confirmation_and_false_break(self):
        b=bars()
        put(b,75,103,104,102,200);put(b,76,103,104,102,100);put(b,77,102,103,101.2,90);put(b,78,100,101,99,100)
        get=lambda n:next(e for e in breakout_events(b[:n],"day") if e["direction"]=="up" and e["lookback"]==20)
        self.assertEqual(get(76)["state"],"candidate")
        self.assertEqual(get(77)["state"],"confirmed")
        self.assertEqual(get(78)["state"],"retest")
        self.assertEqual(get(79)["state"],"false_breakout")
        self.assertEqual(get(77)["level"],101)
    def test_failed_next_bar_and_mirror(self):
        b=bars();put(b,75,97,98,96,200);put(b,76,100,101,99,100)
        z=next(e for e in breakout_events(b[:77],"day") if e["direction"]=="down" and e["lookback"]==20)
        self.assertEqual(z["state"],"false_breakout")
    def test_no_volume_or_lookahead(self):
        b=bars();put(b,75,103,104,102,120)
        self.assertFalse(breakout_events(b[:76],"day"))
        put(b,75,103,104,102,200)
        self.assertFalse(breakout_events(b[:75],"day"))
    def test_pivot_requires_observed_rejection(self):
        b=bars();put(b,70,98,99,95,100)
        for i in (71,72,73):put(b,i,100,101,99,100)
        self.assertFalse(any(e["formation"]==b[70]["date"] for e in pivot_events(b[:73],"day")))
        self.assertTrue(any(e["formation"]==b[70]["date"] and e["confirmed"]==b[73]["date"] for e in pivot_events(b[:74],"day")))
    def test_zones_evidence_and_invalidation(self):
        b=bars();ds=[x["date"] for x in b];a=2
        def e(i,p,side="support",freq="day"):
            return {"price":p,"side":side,"frequency":freq,"formation":ds[i],"confirmed":ds[i+3],"rejection_atr":2}
        events=[e(40,97),e(41,97.2,freq="week"),e(50,97.5),e(65,100.1,"resistance")]
        z=valid_zones(events,b,a,ds,{"ma20":97.2})
        self.assertEqual(z["support"][0]["touches"],2);self.assertEqual(z["support"][0]["ma_confluence"],["ma20"])
        self.assertFalse(z["resistance"]) # a single level cannot create valid RR
        put(b,70,95,96,94,100);put(b,71,95,96,94,100)
        self.assertFalse(valid_zones(events,b,a,ds)["support"])
    def test_role_reversal_needs_three_observed_closes(self):
        b=bars()
        put(b,75,103,104,102,200);put(b,76,103,104,102,100);put(b,77,102,103,101.2,90)
        for i in (78,79,80):put(b,i,104,105,103,100)
        self.assertFalse(role_reversal_events(b[:80],"day"))
        self.assertTrue(any(e.get("role_reversal") and e["confirmed"]==b[80]["date"] for e in role_reversal_events(b[:81],"day")))
    def test_calendar_gap(self):
        b=bars();ds=[x["date"] for x in b]
        self.assertEqual(len(contiguous_tail(b[:-3]+b[-2:],"day",ds,ds[-1])),2)
    def test_gate_and_holding_review(self):
        r={"asof":"20261127","composite_ready":True,"market_industry_context":{"state":"context_ready","block_new_exposure":False},
           "cycles":{"week":{"trend":"bullish","provisional":False},"month":{"trend":"range"}},"horizons":{"short":{"D":30}}}
        l={"risk_veto":False,"price":100,"invalidation":95,"target_reference":112,"reward_risk":2.4,
           "breakouts":[{"direction":"up","state":"candidate","frequency":"day","event_date":r["asof"]}]}
        self.assertEqual(conditional_plan(r,l)["new_exposure"],"portfolio_permission_unverified_or_denied")
        self.assertEqual(conditional_plan(r,l,False,True)["new_exposure"],"conditional_opportunity")
        r["cycles"]["week"]["provisional"]=True
        self.assertEqual(conditional_plan(r,l,False,True)["new_exposure"],"watch")
        l["completed_week_trend"]="bullish"
        self.assertEqual(conditional_plan(r,l,False,True)["new_exposure"],"conditional_opportunity")
        r["market_industry_context"]["state"]="defensive";r["cycles"]["week"]["trend"]="bearish"
        p=conditional_plan(r,l,True,True)
        self.assertEqual(p["new_exposure"],"defensive_no_new_exposure");self.assertEqual(p["holding_review"],"review_risk")
        r["market_industry_context"]={"state":"context_ready","block_new_exposure":None}
        self.assertEqual(conditional_plan(r,l,True,True)["new_exposure"],"evidence_insufficient_context_or_risk")
if __name__=="__main__":unittest.main()
