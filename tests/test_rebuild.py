"""수집 보강분과 사이트 생성기 테스트. 표준 unittest만 쓴다.

  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "sitegen"))

import build  # noqa: E402
import collect  # noqa: E402
import edgar  # noqa: E402
import parse_13f  # noqa: E402
import tickers  # noqa: E402


def table(rows):
    """[(cusip, shares, value)] -> 13F information table XML."""
    body = "".join(
        f"<infoTable><nameOfIssuer>{c}</nameOfIssuer><titleOfClass>COM</titleOfClass>"
        f"<cusip>{c}</cusip><value>{v}</value><shrsOrPrnAmt><sshPrnamt>{s}</sshPrnamt>"
        f"<sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>" for c, s, v in rows)
    return f'<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">{body}</informationTable>'


class TestNamespaces(unittest.TestCase):
    """실제 공시에서 파싱이 깨졌던 모양: 접두사 붙은 태그와 xsi: 속성."""

    XML = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<ns1:informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://www.sec.gov/edgar/document/thirteenf/informationtable eis_13FDocument.xsd">'
           '<ns1:infoTable><ns1:nameOfIssuer>UBER TECHNOLOGIES INC</ns1:nameOfIssuer><ns1:titleOfClass>COM</ns1:titleOfClass>'
           '<ns1:cusip>90353T100</ns1:cusip><ns1:value>2350000000</ns1:value>'
           '<ns1:shrsOrPrnAmt><ns1:sshPrnamt>34268000</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>'
           '<ns1:putCall>Call</ns1:putCall></ns1:infoTable></ns1:informationTable>')

    def test_prefixed_table_with_xsi_attribute(self):
        rows = parse_13f.parse_info_table(self.XML, "2026-09-30")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].cusip, rows[0].shares, rows[0].value, rows[0].put_call),
                         ("90353T100", 34268000, 2350000000, "CALL"))


class TestUnits(unittest.TestCase):
    def _mk(self, shares, value, stype="SH"):
        return parse_13f.RawHolding("X", "X", "COM", value, shares, stype, "")

    def test_thousands_are_scaled_to_dollars(self):
        hs = [self._mk(4_000_000, 933_000), self._mk(1_000_000, 175_430), self._mk(3_000_000, 389_540)]
        self.assertEqual(collect.normalize_units(hs), 1000)
        self.assertEqual(hs[0].value, 933_000_000)

    def test_dollars_are_left_alone_even_with_one_penny_stock(self):
        hs = [self._mk(100, 23_000), self._mk(100, 15_000), self._mk(1_000_000, 400_000)]
        self.assertEqual(collect.normalize_units(hs), 1)
        self.assertEqual(hs[2].value, 400_000)


class TestTickers(unittest.TestCase):
    def test_prefers_us_composite_and_normalizes_share_class(self):
        res = {"data": [{"ticker": "BRK/B", "exchCode": "UN", "marketSector": "Equity", "securityType": "Common Stock"},
                        {"ticker": "BRK/B", "exchCode": "US", "marketSector": "Equity", "securityType": "Common Stock"},
                        {"ticker": "BRYN", "exchCode": "GR", "marketSector": "Equity"}]}
        self.assertEqual(tickers.pick(res), {"ticker": "BRK.B", "type": "Common Stock"})

    def test_not_found_and_unusable_tickers(self):
        self.assertIsNone(tickers.pick({"warning": "No identifier found."}))
        self.assertIsNone(tickers.pick({"data": [{"ticker": "BAC PR L", "exchCode": "US"}]}))

    def test_job_uses_cins_for_letter_prefixed_ids(self):
        self.assertEqual(tickers.job("037833100", True), {"idType": "ID_CUSIP", "idValue": "037833100", "exchCode": "US"})
        self.assertEqual(tickers.job("H1467J104", False), {"idType": "ID_CINS", "idValue": "H1467J104"})
        self.assertEqual(tickers.job("H1467J104", False, swap=True)["idType"], "ID_CUSIP")

    def test_site_map_lets_manual_entries_win(self):
        tmap = build.load_tmap()
        self.assertEqual(tmap["037833100"]["ticker"], "AAPL")


class TestSources(unittest.TestCase):
    """공시 주체가 바뀐 큰손: 분기마다 어느 CIK 것을 쓸지."""

    def setUp(self):
        self._orig = edgar.list_13f_filings_with_name
        new = [edgar.Filing("N-3", "13F-HR", "2026-11-16", "2026-09-30"), edgar.Filing("N-2", "13F-HR", "2026-08-14", "2026-06-30"),
               edgar.Filing("N-1", "13F-HR", "2026-05-15", "2026-03-31")]
        old = [edgar.Filing("O-1", "13F-HR", "2026-05-15", "2026-03-31"), edgar.Filing("O-0", "13F-HR", "2026-02-17", "2025-12-31")]
        edgar.list_13f_filings_with_name = lambda cik: ("PERSHING SQUARE INC.", new) if cik == 2 else ("Pershing Square Capital Management, L.P.", old)

    def tearDown(self):
        edgar.list_13f_filings_with_name = self._orig

    def test_each_period_comes_from_the_right_filer(self):
        m = {"slug": "p", "cik": 2, "expect": "PERSHING SQUARE",
             "sources": [{"cik": 2, "from": "2026-06-30"}, {"cik": 1, "until": "2026-03-31"}]}
        plan = collect.plan_periods(m)
        self.assertEqual({p: v[0] for p, v in plan.items()},
                         {"2026-09-30": 2, "2026-06-30": 2, "2026-03-31": 1, "2025-12-31": 1})
        self.assertEqual(plan["2026-03-31"][2][0].accession, "O-1")

    def test_wrong_name_is_skipped(self):
        self.assertEqual(collect.plan_periods({"slug": "x", "cik": 2, "expect": "BERKSHIRE"}), {})


class TestPickInfoTable(unittest.TestCase):
    def test_skips_cover_page_even_with_xsl_prefix(self):
        items = [{"name": "primary_doc.xml", "size": "2027"}, {"name": "form13f_20250930.xml", "size": "25360"}]
        self.assertEqual(edgar.pick_info_table(items, "xslForm13F_X02/primary_doc.xml"), "form13f_20250930.xml")

    def test_prefers_named_table_then_largest(self):
        items = [{"name": "primary_doc.xml", "size": "900000"}, {"name": "x.xml", "size": "10"},
                 {"name": "infotable.xml", "size": "5"}]
        self.assertEqual(edgar.pick_info_table(items, "primary_doc.xml"), "infotable.xml")
        items = [{"name": "primary_doc.xml", "size": "3"}, {"name": "a.xml", "size": "10"}, {"name": "50240.xml", "size": "999"}]
        self.assertEqual(edgar.pick_info_table(items, "primary_doc.xml"), "50240.xml")

    def test_no_table(self):
        self.assertEqual(edgar.pick_info_table([{"name": "primary_doc.xml"}], "primary_doc.xml"), "")


class TestAmendments(unittest.TestCase):
    """2025 Q1 버크셔처럼, 원본 뒤에 종목 몇 개짜리 정정 공시가 붙는 경우."""

    def setUp(self):
        self.xml, self.kind = {}, {}
        self._fx, self._ft = edgar.fetch_info_table_xml, edgar.fetch_amendment_type
        edgar.fetch_info_table_xml = lambda cik, f: self.xml[f.accession]
        edgar.fetch_amendment_type = lambda cik, f: self.kind.get(f.accession, "")

    def tearDown(self):
        edgar.fetch_info_table_xml, edgar.fetch_amendment_type = self._fx, self._ft

    def _group(self):
        base = edgar.Filing("A-1", "13F-HR", "2025-05-15", "2025-03-31")
        amd = edgar.Filing("A-2", "13F-HR/A", "2025-08-14", "2025-03-31")
        self.xml["A-1"] = table([("AAA", 10, 100), ("BBB", 20, 200), ("CCC", 30, 300), ("DDD", 40, 400)])
        self.xml["A-2"] = table([("EEE", 5, 50)])
        return [base, amd]

    def test_new_holdings_are_added_not_replacing(self):
        group = self._group()
        self.kind["A-2"] = "NEW HOLDINGS"
        got = collect.build_period(1, group, "2025-03-31")
        self.assertEqual(sorted(h.cusip for h in got), ["AAA", "BBB", "CCC", "DDD", "EEE"])
        self.assertEqual(parse_13f.total_value(got), 1050)

    def test_unreadable_cover_falls_back_to_size(self):
        got = collect.build_period(1, self._group(), "2025-03-31")  # 표지를 못 읽음
        self.assertEqual(len(got), 5)

    def test_restatement_replaces(self):
        group = self._group()
        self.kind["A-2"] = "RESTATEMENT"
        got = collect.build_period(1, group, "2025-03-31")
        self.assertEqual([h.cusip for h in got], ["EEE"])

    def test_row_keeps_cusip(self):
        h = parse_13f.RawHolding("037833100", "APPLE INC", "COM", 1000, 10, "SH", "")
        row = collect.to_row(h, {"037833100": {"ticker": "AAPL", "name": "Apple Inc", "cl": ""}})
        self.assertEqual(row, ["AAPL", "Apple Inc", "", 10, 1000, "037833100"])


def q(period, rows):
    rs = [{"key": k, "ticker": k, "name": k, "cl": "", "opt": "", "cusip": "", "mapped": True,
           "shares": s, "value": v} for k, s, v in rows]
    total = sum(r["value"] for r in rs)
    for r in rs:
        r["w"] = r["value"] / total * 100
    return {"period": period, "meta": {}, "rows": rs, "total": total}


class TestSiteDiff(unittest.TestCase):
    def test_statuses_and_estimates(self):
        prev = q("2026-06-30", [("AAA", 100, 1000), ("BBB", 100, 1000), ("CCC", 100, 1000), ("DDD", 100, 700)])
        cur = q("2026-09-30", [("AAA", 150, 3000), ("BBB", 60, 600), ("CCC", 100, 1100), ("EEE", 10, 500)])
        mv = build.diff(cur, prev)
        by = {r["key"]: r for r in cur["rows"]}
        self.assertEqual([by[k]["st"] for k in ("AAA", "BBB", "CCC", "EEE")], ["add", "trim", "keep", "new"])
        self.assertAlmostEqual(by["AAA"]["pct"], 50.0)
        self.assertAlmostEqual(by["AAA"]["est"], 50 * 20)      # 늘린 50주 × 분기 말 가격 20
        self.assertAlmostEqual(by["BBB"]["est"], 40 * 10)
        self.assertEqual((mv["n_new"], mv["n_add"], mv["n_trim"], mv["n_exit"]), (1, 1, 1, 1))
        self.assertAlmostEqual(mv["buy_total"], 1000 + 500)
        self.assertAlmostEqual(mv["sell_total"], 400 + 700)     # 청산은 전분기 말 평가액

    def test_no_previous_quarter(self):
        cur = q("2026-09-30", [("AAA", 1, 1)])
        self.assertIsNone(build.diff(cur, None))
        self.assertEqual(cur["rows"][0]["st"], "base")

    def test_prev_period_wraps_year(self):
        self.assertEqual(build.prev_period("2026-03-31"), "2025-12-31")
        self.assertEqual(build.prev_period("2026-09-30"), "2026-06-30")


class TestTreemap(unittest.TestCase):
    def test_tiles_fill_the_box_without_overlap_in_area(self):
        items = [(i, a) for i, a in enumerate([50, 20, 10, 8, 6, 3, 2, 1])]
        rects = build.squarify(items, 760, 520)
        self.assertEqual(len(rects), len(items))
        self.assertAlmostEqual(sum(w * h for _, _, _, w, h in rects), 760 * 520, places=3)
        for _, x, y, w, h in rects:
            self.assertGreaterEqual(x, -1e-6)
            self.assertLessEqual(x + w, 760 + 1e-6)
            self.assertLessEqual(y + h, 520 + 1e-6)


class TestKeyNormalization(unittest.TestCase):
    def test_repo_snapshots_have_no_cusip_only_rows_left_in_latest(self):
        tmap = build._json(os.path.join(ROOT, "pipeline", "ticker_map.json"), {})["by_cusip"]
        m = {"slug": "berkshire"}
        quarters = build.load_manager(m, tmap)
        self.assertTrue(quarters)
        self.assertEqual([r["ticker"] for r in quarters[-1]["rows"] if not r["mapped"]], [])
        # 같은 종목이 분기마다 다른 키(티커 / CUSIP)로 잡혀 신규·청산으로 보이면 안 된다
        keys = [{r["key"] for r in x["rows"]} for x in quarters[-3:]]
        self.assertIn("SIRI", keys[0] & keys[1] & keys[2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
