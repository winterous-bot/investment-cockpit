import unittest
from datetime import datetime,timedelta
from technical.e1_manifest import schedule,sampling,panel_counts,split
class E1Test(unittest.TestCase):
    def test_purge_and_week_boundary(self):
        start=datetime(2022,12,1);stop=datetime(2026,12,31)
        cal=[(start+timedelta(days=i)).strftime("%Y%m%d") for i in range((stop-start).days+1) if (start+timedelta(days=i)).weekday()<5]
        qs,last=schedule(cal);self.assertEqual(len(qs),16)
        for name in last:
            rows=[r for q in qs.values() for r in q if r["split"]==name]
            self.assertEqual(sum(r["purged"] for r in rows),40)
            self.assertEqual(rows[-41]["label_end_by_horizon"]["40"],last[name])
            self.assertIsNone(rows[-40]["label_end_by_horizon"]["40"])
            self.assertFalse(rows[-41]["purged"])
        # 2024-12-31 is Tuesday: weekly observation must fall next year, not split-end.
        self.assertFalse(qs["2024Q4"][-1]["weekly"])
        self.assertEqual(split("20250103"),"validation")
    def test_nested_sample_and_delist(self):
        u={f"600{i:03d}.SH":("20200101",None) for i in range(1,301)}
        u["600001.SH"]=("20200101","20230301")
        u["600002.SH"]=("20200101","20221201")
        u["002475.SZ"]=("20200101",None)
        u["300999.SZ"]=("20240101",None)
        amounts={(datetime(2022,12,1)+timedelta(days=i)).strftime("%Y%m%d"):{k:j+1 for j,k in enumerate(sorted(u))} for i in range(20)}
        m=sampling(u,"20230103",amounts,"2023Q1")
        a={k for v in m["core"].values() for k in v};b={k for v in m["daily"].values() for k in v}
        self.assertEqual((len(a),len(b)),(240,60));self.assertTrue(b<=a)
        self.assertFalse(a&{"600002.SH","002475.SZ","300999.SZ"})
        self.assertEqual(m["board_scope_count"],299)
        self.assertEqual(m,sampling(dict(reversed(list(u.items()))),"20230103",amounts,"2023Q1"))
    def test_panel_denominators(self):
        rows=[{"weekly":True,"purged":False},{"weekly":False,"purged":False},{"weekly":True,"purged":True}]
        x=panel_counts(rows,240,60)
        self.assertEqual(x["core"],{"planned":480,"purged":240,"after_purge":240})
        self.assertEqual(x["daily"]["planned"],180);self.assertEqual(x["overlap"]["planned"],120)
