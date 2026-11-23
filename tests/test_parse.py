"""Unit tests for the 13F parser. Pure stdlib unittest.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import parse_13f  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_infotable.xml")


class TestParseInfoTable(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as f:
            self.xml = f.read()
        self.rows = parse_13f.parse_info_table(self.xml, "2026-03-31")
        self.by_key = {r.key: r for r in self.rows}

    def test_three_positions_after_aggregation(self):
        # Apple has two lots -> one key; plus KO and the OXY call.
        self.assertEqual(len(self.rows), 3)
        self.assertIn("037833100", self.by_key)
        self.assertIn("191216100", self.by_key)
        self.assertIn("674599105:CALL", self.by_key)

    def test_apple_lots_aggregated(self):
        aapl = self.by_key["037833100"]
        self.assertEqual(aapl.shares, 150)      # 100 + 50
        self.assertEqual(aapl.value, 1500)      # 1000 + 500 (dollars, mult=1)

    def test_total_value(self):
        self.assertEqual(parse_13f.total_value(self.rows), 3600)

    def test_option_key_is_separate(self):
        oxy = self.by_key["674599105:CALL"]
        self.assertEqual(oxy.put_call, "CALL")
        self.assertEqual(oxy.shares, 10)

    def test_value_multiplier_boundary(self):
        # Pre-2023Q3 values are in thousands.
        self.assertEqual(parse_13f.value_multiplier_for_period("2022-06-30"), 1000)
        self.assertEqual(parse_13f.value_multiplier_for_period("2023-09-30"), 1)
        self.assertEqual(parse_13f.value_multiplier_for_period("2026-03-31"), 1)

    def test_multiplier_applied_to_old_period(self):
        old = parse_13f.parse_info_table(self.xml, "2022-06-30")
        aapl = {r.key: r for r in old}["037833100"]
        self.assertEqual(aapl.value, 1500 * 1000)


class TestMergeAmendment(unittest.TestCase):
    def _mk(self, cusip, shares, value):
        return parse_13f.RawHolding(cusip=cusip, name=cusip, title_of_class="COM",
                                    value=value, shares=shares, share_type="SH",
                                    put_call="")

    def test_restatement_replaces(self):
        base = [self._mk("AAA", 10, 100), self._mk("BBB", 20, 200)]
        amend = [self._mk("AAA", 99, 999)]
        merged = parse_13f.merge_amendment(base, amend, "RESTATEMENT")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].shares, 99)

    def test_new_holdings_unions(self):
        base = [self._mk("AAA", 10, 100)]
        amend = [self._mk("BBB", 20, 200)]
        merged = parse_13f.merge_amendment(base, amend, "NEW HOLDINGS")
        keys = sorted(h.key for h in merged)
        self.assertEqual(keys, ["AAA", "BBB"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
