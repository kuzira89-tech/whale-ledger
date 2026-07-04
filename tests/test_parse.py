"""Unit tests for the 13F parser and diff logic. Pure stdlib unittest.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import parse_13f  # noqa: E402
import build_site_data as bsd  # noqa: E402

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


class TestDiff(unittest.TestCase):
    def _h(self, ticker, shares, value):
        return {"key": ticker, "ticker": ticker, "name": ticker, "cl": "",
                "shares": shares, "value": value}

    def test_new_add_trim_keep_and_exit(self):
        prev = [self._h("AAA", 100, 1000), self._h("BBB", 100, 1000),
                self._h("CCC", 100, 1000), self._h("DDD", 100, 1000)]
        cur = [self._h("AAA", 150, 1500),   # ADD
               self._h("BBB", 60, 600),     # TRIM
               self._h("CCC", 100, 1000),   # KEEP
               self._h("EEE", 100, 1000)]   # NEW ; DDD exits
        holdings, exits, stats = bsd._diff(cur, prev)
        by = {h["ticker"]: h for h in holdings}
        self.assertEqual(by["AAA"]["status"], "ADD")
        self.assertEqual(by["BBB"]["status"], "TRIM")
        self.assertEqual(by["CCC"]["status"], "KEEP")
        self.assertEqual(by["EEE"]["status"], "NEW")
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["exited"], 1)
        self.assertEqual(exits[0]["ticker"], "DDD")

    def test_base_quarter_has_no_diff(self):
        cur = [self._h("AAA", 100, 1000)]
        holdings, exits, stats = bsd._diff(cur, None)
        self.assertEqual(holdings[0]["status"], "HOLD")
        self.assertEqual(exits, [])

    def test_weights_sum_to_100(self):
        cur = [self._h("AAA", 1, 300), self._h("BBB", 1, 700)]
        holdings, _, _ = bsd._diff(cur, None)
        self.assertAlmostEqual(sum(h["weight"] for h in holdings), 100.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
