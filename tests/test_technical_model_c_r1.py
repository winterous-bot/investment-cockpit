import unittest
from datetime import date,timedelta
from technical.model_c_r1 import zones_for,horizon_location,trend_tracking
def fixture():
    ds=[(date(2026,1,1)+timedelta(days=i)).strftime("%Y%m%d") for i in range(100)]
    daily=[{"date":d,"close":100,"low":99,"high":101} for d in ds]
    def e(i,p,side="resistance",kind="rejection",freq="day"):
        return {"price":p,"side":side,"kind":kind,"frequency":freq,"formation":ds[i],"confirmed":ds[i+3]}
    return ds,daily,e
class R1Test(unittest.TestCase):
    def test_near_B_blocks_remote_A(self):
        ds,b,e=fixture();events=[e(70,102,kind="range_extreme"),e(60,115),e(80,115.2),e(70,98,"support"),e(80,98.1,"support")]
        z=zones_for(events,b,2,ds,("day",))
        l=horizon_location("short",100,2,2,z,[],False)
        self.assertEqual(l["target_reference"],102)
        self.assertEqual(l["resistance"]["grade"],"B")
        self.assertEqual(l["remote_resistance"][0]["grade"],"A")
        self.assertLess(l["reward_risk"],2)
    def test_far_target_null_and_separate_scale(self):
        ds,b,e=fixture();events=[e(70,110),e(80,110.2),e(70,98,"support")]
        a=horizon_location("short",100,2,2,zones_for(events,b,2,ds,("day",)),[],False)
        m=horizon_location("medium",100,5,2,zones_for(events,b,5,ds,("day","week")),[],False)
        self.assertIsNone(a["reward_risk"]);self.assertEqual(a["target_status"],"remote_only")
        self.assertEqual(m["target_reference"],110);self.assertEqual(m["invalidation"],95.5)
    def test_no_untested_stop_or_monthly_target(self):
        ds,b,e=fixture();events=[e(70,99,"support","range_extreme"),e(80,105,freq="month")]
        z=zones_for(events,b,2,ds,("day","week"))
        a=horizon_location("short",100,2,2,z,[],False)
        self.assertIsNone(a["invalidation"]);self.assertIsNone(a["target_reference"]);self.assertTrue(a["risk_veto"])
    def test_invalidated_episode_not_resurrected(self):
        ds,b,e=fixture();b[65]["close"]=95;b[66]["close"]=95
        z=zones_for([e(50,98,"support"),e(75,98,"support")],b,2,ds,("day",))
        self.assertEqual(z["support"][0]["grade"],"B");self.assertEqual(z["support"][0]["touches"],1)
    def test_duplicate_and_opposite_side_not_A(self):
        ds,b,e=fixture();z=zones_for([e(75,102),e(76,102.2,freq="week"),e(85,102.1,"support")],b,2,ds,("day","week"))
        self.assertEqual(z["resistance"][0]["grade"],"B");self.assertEqual(z["resistance"][0]["touches"],1)
    def test_price_on_obstacle_blocks(self):
        ds,b,e=fixture();z=zones_for([e(70,100,kind="range_extreme"),e(75,104),e(80,98,"support")],b,2,ds,("day",))
        a=horizon_location("short",100,2,2,z,[],False)
        self.assertIsNone(a["target_reference"]);self.assertTrue(a["flags"]["unresolved_obstacle"])
    def test_tracking_no_target_no_permission(self):
        ds,b,e=fixture();r={"composite_ready":True,"cycles":{"week":{"trend":"bullish"},"month":{"trend":"range"}},"horizons":{"medium":{"D":60}}}
        l={"target_status":"no_structural_resistance","daily_atr14":2,"completed_week_trend":"bullish"}
        t=trend_tracking(r,l,b);self.assertEqual(t["state"],"research_watch_only");self.assertIsNone(t["reward_risk"]);self.assertFalse(t["new_exposure_allowed"])
        l["target_status"]="within_horizon";self.assertIsNone(trend_tracking(r,l,b))
    def test_missing_scale_and_overextended_stop(self):
        ds,b,e=fixture();z=zones_for([e(70,94.5,"support"),e(80,105)],b,2,ds,("day",))
        a=horizon_location("short",100,2,2,z,[],False)
        self.assertIsNone(a["invalidation"]);self.assertTrue(a["risk_veto"])
        self.assertTrue(horizon_location("medium",100,None,2,z,[],False)["risk_veto"])
if __name__=="__main__":unittest.main()
