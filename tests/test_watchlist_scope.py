import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"company"),str(ROOT/"growth")]
from company import watchlist_build as w
from company import build as frozen
class WatchlistScopeTests(unittest.TestCase):
    def test_empty_and_valid(self):
        self.assertEqual(w.valid_codes([]),[])
        self.assertEqual(w.valid_codes(["002475.SZ","600001.SH"]),["002475.SZ","600001.SH"])
    def test_reject_duplicate_or_other_market(self):
        for x in (["002475.SZ","002475.SZ"],["830001.BJ"],["../"],["002475"],[1],["%06d.SZ"%i for i in range(21)]):
            with self.assertRaises(ValueError):w.valid_codes(x)
    def test_frozen_engine(self):
        self.assertIs(w.load_company,frozen.load_company)
        self.assertIs(w.profile,frozen.profile)
        self.assertIs(w.fe.reconstruct,frozen.fe.reconstruct)
if __name__=="__main__":unittest.main()
