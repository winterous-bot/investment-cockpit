import unittest
from copy import deepcopy
from technical.model_d import compose,render
def fixture():
    d="20261127";code="002475.SZ"
    h={k:{"T":0,"M":0,"V":{"V":0},"R":{"R":0},"D":0,"direction":"mixed"} for k in ("short","medium")}
    cy={f:{"T":0,"M":0,"trend":"range","provisional":f=="month","latest_completed_date":d if f!="month" else "20261030"} for f in ("day","week","month")}
    a={"asof":d,"code":code,"horizons":h,"cycles":cy,"quality":{"state":"ready","event_counts":{}},"composite_ready":True,"alignment":"mixed","medium_structure":"conflicting_or_range","weekly_reversal":{"state":"none"},"probability":None}
    m={"score":1,"coverage":100,"asof":d,"state":"weak"}
    ctx={"state":"defensive","block_new_exposure":True,"market_ready":True,"breadth_ready":True,"liquidity_ready":True,"industry_ready":True}
    i={"membership":{"asof":d,"state":"matched","name":"电子"},"trend":m,"industry_vs_market":{"values":{"20":-3},"relative_state":"underperforming"},"stock_vs_industry":{"5":1,"20":2,"60":3}}
    b={**a,"market":{k:dict(m) for k in ("trend","breadth","activity")},"industry":i,"market_industry_context":ctx}
    l={"risk_veto":True,"flags":{"missing_level":True,"unfavorable_rr":None},"breakouts":[],"reward_risk":None,"invalidation":None,"target_reference":None}
    r={"asof":d,"code":code,"direction_scores":h,"probability":None,"locations":{"short":dict(l),"medium":dict(l)},"monthly_background":{},"monthly_dynamic":[],"trend_tracking":None,"coverage":{},"plan":{"new_exposure":"defensive_no_new_exposure","holding_review":"holding_status_unknown"}}
    v={"asof":d,"groups":{f:{"indicators":{},"signals":{},"count":100} for f in cy}}
    return a,b,r,v
class ModelDTest(unittest.TestCase):
    def test_null_and_provisional(self):
        a,b,r,v=fixture();s=compose(a,b,r,v,50);t=render(s)
        self.assertIn("未收完",t);self.assertIn("不可计算",t);self.assertIn("暂缓新增风险敞口",t)
        self.assertIn("实际持仓：未知",t);self.assertIn("未来上涨概率：未建模",t)
        self.assertIsNone(s["probability"])
    def test_stale_display(self):
        a,b,r,v=fixture();b["market"]["trend"]["asof"]="20261126";b["market_industry_context"]["market_ready"]=False
        t=render(compose(a,b,r,v,50));self.assertIn("缺失或日期不一致",t)
        self.assertIn("market_ready",compose(a,b,r,v,50)["gaps"])
    def test_identity_and_score_invariants(self):
        a,b,r,v=fixture();r["code"]="X"
        with self.assertRaises(ValueError):compose(a,b,r,v,50)
        a,b,r,v=fixture();r["direction_scores"]=deepcopy(a["horizons"]);r["direction_scores"]["short"]["D"]=99
        with self.assertRaises(ValueError):compose(a,b,r,v,50)
        a,b,r,v=fixture();a["probability"]=.8
        with self.assertRaises(ValueError):compose(a,b,r,v,50)
    def test_permission_guard(self):
        a,b,r,v=fixture();r["plan"]["new_exposure"]="conditional_opportunity"
        with self.assertRaises(ValueError):compose(a,b,r,v,50)
        b["market_industry_context"].update(state="context_ready",block_new_exposure=False)
        r["locations"]["short"]["risk_veto"]=False
        r["plan"].update(reference_entry=50,reference_invalidation=48,reference_target=55)
        with self.assertRaises(ValueError):compose(a,b,r,v,50,portfolio_permission=True)
        s=compose(a,b,r,v,50,portfolio_permission=True,severe_risk=False)
        self.assertIn("非成交指令",render(s))
if __name__=="__main__":unittest.main()
