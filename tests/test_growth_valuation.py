import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"growth"))
from valuation_model import percentile,reference,verified_quote,historical,peer_reference,completed_month_ends,enrich
class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.x={"code":"000001.SZ","industry":"设备","market_cap":100,"pe":20,"deducted_pe":25,"revenue_cagr":.2,"deducted_yoy":.3,"roic":.15,"cash_conversion":1,"debt_ratio":.4}
        self.day="20261125"
        self.q={"trade_date":self.day,"close":10,"pe_ttm":20,"total_mv":1000000,"total_share":100000}
        self.z=verified_quote(self.x,self.q,self.day)
        self.dates=[f"{2023+i//12}{1+i%12:02d}28" for i in range(36)]
    def test_quartiles(self):
        self.assertEqual(reference([10,20,30,40,50],.5,10)["price"],[10,15,20])
        self.assertAlmostEqual(reference([10,20,30],.5,10)["relative_to_median"],0)
    def test_quote(self):
        self.assertTrue(self.z["share_ok"])
        self.assertFalse(verified_quote(self.x,{**self.q,"total_share":200000},self.day)["share_ok"])
        self.assertFalse(verified_quote(self.x,{**self.q,"pe_ttm":25},self.day)["consistent"])
        self.assertIsNone(verified_quote(self.x,{**self.q,"trade_date":"20261124"},self.day))
    def test_history(self):
        h={d:30 for d in self.dates}
        r=historical(self.x,self.z,h,self.dates);self.assertEqual(r["price"],[15,15,15])
        self.assertEqual(r["percentile"],0);self.assertEqual(r["n"],36)
        h={d:30 for d in self.dates[12:]}
        self.assertIsNone(historical(self.x,self.z,h,self.dates))
        self.assertIsNone(historical(self.x,{**self.z,"pe":None},h,self.dates))
    def test_peers(self):
        cohort=[{**self.x,"code":str(i),"deducted_pe":30} for i in range(8)]
        p,c=peer_reference(self.x,self.z,cohort+[self.x]);self.assertEqual(p["n"],8);self.assertEqual(p["price"],[12,12,12])
        p,c=peer_reference(self.x,self.z,cohort[:7]);self.assertIsNone(p);self.assertIsNone(c)
        p,c=peer_reference(self.x,self.z,[{**v,"roic":.30} for v in cohort]);self.assertIsNone(p);self.assertEqual(c["n"],8)
    def test_months(self):
        cal=[{"cal_date":f"{2023+i//12}{1+i%12:02d}28","is_open":1} for i in range(48)]
        dates=completed_month_ends(cal,"20261125")
        self.assertEqual((dates[0],dates[-1],len(dates)),("20231128","20261028",36))
        with self.assertRaises(ValueError):completed_month_ends(cal[:12],"20261125")
    def test_enrich_preserves_screen(self):
        rows=[self.x.copy()];stats=enrich(rows,{self.x["code"]:self.q},{self.x["code"]:{d:30 for d in self.dates}},self.dates,self.day)
        self.assertEqual(stats["all"]["historical"],1);self.assertEqual(rows[0]["roic"],.15)
        self.assertEqual(rows[0]["valuation"]["close"],10)
if __name__=="__main__":unittest.main()
