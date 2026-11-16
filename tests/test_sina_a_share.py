"""No-network tests of Sina Finance alternative quote parser."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import sina_a_share as s

class SinaAQuoteTest(unittest.TestCase):
    def test_parse_stock(self):
        code,row=s.parse_stock({"code":"002475","name":"立讯精密","trade":"52.36",
            "changepercent":"1.20","amount":"1200000","volume":"10000","pricechange":"0.62"})
        self.assertEqual(code,"002475")
        self.assertEqual(row["price"],52.36)
        self.assertEqual(row["change"],1.2)
        self.assertEqual(row["volume_hands"],100)
        self.assertIsNone(row["trade_at"])
    def test_reject_missing_or_halted(self):
        self.assertIsNone(s.parse_stock({"code":"002475","trade":"0"}))
        self.assertIsNone(s.parse_stock({"code":"475","trade":"1.2"}))
    def test_page_parser(self):
        self.assertEqual(len(s.parse_page('[{"code":"002475","trade":"10"}]')),1)
        with self.assertRaises(ValueError):s.parse_page('{"data":[]}')
if __name__=="__main__":unittest.main()
