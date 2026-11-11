"""Public smoke test with a deliberately empty local data directory."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.vn30_expansion import run_vn30


class ExpansionTests(unittest.TestCase):
    def test_empty_checkout_reports_all_official_tickers(self):
        expected = json.loads(run_vn30.UNIVERSE_CONFIG.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'out'
            with patch.multiple(run_vn30, ROOT=root, OUT=output), patch('builtins.print'):
                self.assertEqual(run_vn30.run(), 0)
            summary = json.loads((output / 'SUMMARY.json').read_text(encoding='utf-8'))
            with (output / 'VN30_FUNNEL.csv').open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 30)
        self.assertEqual(len(set(expected['tickers'])), 30)
        self.assertEqual([row['ticker'] for row in rows], expected['tickers'])
        self.assertTrue(all(row['status'] == 'MISSING_15M_OHLCV' for row in rows))
        self.assertEqual(summary['processed'], 0)
        self.assertEqual(summary['errors'], [])
        self.assertEqual(summary['rules_version'], 'L3_REVERSAL_V1')
