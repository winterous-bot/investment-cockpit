import unittest
from technical.e0_r2_acceleration import acceleration,I,quality,model_c
from technical.model_e0 import digest
class R2Test(unittest.TestCase):
    def test_exact_indicators_and_restoration(self):
        old=I.indicators;oldperiod=I.period
        b=[{"close":10+i*.01,"vol":100+i} for i in range(80)]
        ref=old(b,"day")
        with acceleration() as stats:
            self.assertEqual(digest(I.indicators(b,"day")),digest(ref))
            x=I.indicators(b,"day");x["ma5"]=0
            self.assertEqual(I.indicators(b,"day"),ref)
            self.assertEqual(stats["indicator_hits"],2)
            self.assertEqual(model_c.period("20230103","week"),oldperiod("20230103","week"))
        self.assertIs(I.indicators,old);self.assertIs(I.period,oldperiod)
    def test_exception_restoration_and_invalid_date(self):
        old=quality.date
        with self.assertRaises(ValueError):
            with acceleration():quality.date("bad")
        self.assertIs(quality.date,old)
    def test_different_anchor_and_frequency(self):
        b=[{"close":10+i*.01,"vol":100+i} for i in range(80)]
        c=[{**x,"close":x["close"]*2} for x in b]
        expected=[I.indicators(x,f) for x,f in ((b,"day"),(c,"day"),(b,"week"))]
        with acceleration():
            actual=[I.indicators(x,f) for x,f in ((b,"day"),(c,"day"),(b,"week"))]
        self.assertEqual(expected,actual)
