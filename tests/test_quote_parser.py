import importlib.util
import unittest
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / 'scripts' / 'update_quotes.py'
spec = importlib.util.spec_from_file_location('update_quotes', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class QuoteParserTests(unittest.TestCase):
    def test_quote_fields_and_code_zeros(self):
        code, q = mod.quote_row({'f12': '002475', 'f14': '立讯精密', 'f2': 49.51,
                                 'f3': 8.93, 'f4': 4.06, 'f5': 1370000,
                                 'f6': 6565000000, 'f124': 1790000000})
        self.assertEqual(code, '002475')
        self.assertEqual(q['price'], 49.51)
        self.assertEqual(q['change'], 8.93)
        self.assertEqual(q['name'], '立讯精密')

    def test_halt_and_invalid_prices_are_ignored(self):
        self.assertIsNone(mod.quote_row({'f12': '001248', 'f14': 'A', 'f2': '-'}))
        self.assertIsNone(mod.quote_row({'f12': '001248', 'f14': 'A', 'f2': 0}))
        self.assertIsNone(mod.finite_float('-'))
        self.assertIsNone(mod.finite_float(float('nan')))

    def test_empty_or_dict_diff(self):
        self.assertEqual(mod.entries({'data': {'diff': None}}), [])
        self.assertEqual(mod.entries({'data': {'diff': {'0': {'f12': '600089'}}}}), [{'f12': '600089'}])

    def test_index_regime_reference(self):
        raw = mod.download_json
        def mocked(url, params, retries=3):
            return {'data': {'klines': [f'2026-01-01,0,{3000+i*2},0,0,0,0' for i in range(290)]}}
        try:
            mod.download_json = mocked
            result = mod.fetch_index_technical()
            self.assertEqual(result['suggested'], 'bull')
            self.assertGreater(result['ma20'], result['ma60'])
            self.assertGreater(result['ma60'], result['ma250'])
        finally:
            mod.download_json = raw


if __name__ == '__main__':
    unittest.main()
