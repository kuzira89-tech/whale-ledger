"""큰손을 가로지르는 계산(분할, 종목별 현황, 분기 요약)과 미리보기 그림 테스트.

  python -m unittest tests.test_market -v
"""
import os
import struct
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "sitegen"))

import build  # noqa: E402
import market  # noqa: E402
import ogimage  # noqa: E402


def row(ticker, shares, value, mapped=True, opt="", name=None):
    key = ticker + (":" + opt if opt else "")
    return {"key": key, "ticker": ticker, "name": name or f"{ticker} INC", "cl": "", "opt": opt,
            "cusip": "", "mapped": mapped, "shares": shares, "value": value}


def quarter(period, rows):
    total = sum(r["value"] for r in rows) or 1
    rows = sorted(rows, key=lambda r: -r["value"])
    for r in rows:
        r["w"] = r["value"] / total * 100
    return {"period": period, "meta": {}, "rows": rows, "total": total}


def whale(slug, quarters, **extra):
    """분기 목록에 diff 결과(mv)까지 붙인 큰손 한 곳."""
    by = {q["period"]: q for q in quarters}
    for q in quarters:
        q["mv"] = build.diff(q, by.get(build.prev_period(q["period"])), extra.get("splits"))
    m = {"slug": slug, "ko": slug, "en": slug, "cik": 1}
    m.update({k: v for k, v in extra.items() if k != "splits"})
    return {"m": m, "quarters": quarters}


Q1, Q2 = "2026-06-30", "2026-09-30"


class TestSplitGuess(unittest.TestCase):
    def test_label(self):
        self.assertEqual(market.split_label(10), "10:1")
        self.assertEqual(market.split_label(1.5), "3:2")
        self.assertEqual(market.split_label(0.1), "1:10")

    def test_two_for_one(self):
        # 가격이 절반이 되고 보유자들의 주식 수가 두 배 안팎이 됐다.
        self.assertEqual(market.split_factor([(2.017, 0.54), (2.067, 0.54)]), 2)

    def test_holders_who_traded_through_a_split(self):
        # 넷플릭스 10:1. 아무도 정확히 10배가 아니고, 한 곳은 12배에 가깝다.
        obs = [(0.69, 0.078), (12.08, 0.078), (17.55, 0.078), (10.106, 0.078), (10.833, 0.078)]
        self.assertIsNotNone(market.split_factor(obs))

    def test_crash_is_not_a_split(self):
        # 주가가 반 토막 났지만 보유자들의 주식 수는 그대로거나 조금 바뀌었을 뿐이다.
        self.assertIsNone(market.split_factor([(1.0, 0.47), (1.23, 0.47), (1.19, 0.47), (0.85, 0.47)]))
        self.assertIsNone(market.split_factor([(2.46, 0.52), (0.8, 0.52), (1.15, 0.52)]))

    def test_unchanged_holder_rules_out_a_split(self):
        self.assertIsNone(market.split_factor([(1.0, 0.5), (2.0, 0.5)]))

    def test_quiet_price_is_ignored(self):
        self.assertIsNone(market.split_factor([(2.0, 0.95), (2.0, 0.95)]))

    def test_pinned_file(self):
        pinned, vetoed = market.pinned_splits({
            "splits": [{"ticker": "CRWD", "period": Q2, "ratio": 4}],
            "not_splits": [{"ticker": "FMC", "period": Q1}]})
        self.assertEqual(pinned, {("CRWD", Q2): 4.0})
        self.assertEqual(vetoed, {("FMC", Q1)})

    def test_shipped_file_is_consistent(self):
        raw = build._json(os.path.join(ROOT, "pipeline", "splits.json"), {})
        pinned, vetoed = market.pinned_splits(raw)
        self.assertEqual(len(pinned), len(raw["splits"]), "같은 종목·분기가 두 번 적혔다")
        self.assertFalse(set(pinned) & vetoed)
        for s in raw["splits"]:
            self.assertRegex(s["period"], r"^\d{4}-(03-31|06-30|09-30|12-31)$")
            self.assertGreater(s["ratio"], 0)
            self.assertNotEqual(s["ratio"], 1)


class TestDiffWithSplits(unittest.TestCase):
    def test_split_is_not_a_purchase(self):
        prev = quarter(Q1, [row("CRWD", 100, 40000)])
        cur = quarter(Q2, [row("CRWD", 400, 40000)])
        mv = build.diff(cur, prev, {("CRWD", Q2): 4.0})
        self.assertEqual(cur["rows"][0]["st"], "keep")
        self.assertEqual(mv["buys"], [])
        self.assertEqual(mv["splits"], {"CRWD": 4.0})

    def test_trade_on_top_of_a_split(self):
        prev = quarter(Q1, [row("CRWD", 100, 40000)])
        cur = quarter(Q2, [row("CRWD", 500, 50000)])
        build.diff(cur, prev, {("CRWD", Q2): 4.0})
        r = cur["rows"][0]
        self.assertEqual(r["st"], "add")
        self.assertAlmostEqual(r["pct"], 25.0)
        self.assertAlmostEqual(r["est"], 100 * 100)   # 늘어난 100주 × 분기 말 가격 100

    def test_reverse_split(self):
        prev = quarter(Q1, [row("LCID", 1000, 3000)])
        cur = quarter(Q2, [row("LCID", 100, 3000)])
        build.diff(cur, prev, {("LCID", Q2): 0.1})
        self.assertEqual(cur["rows"][0]["st"], "keep")

    def test_without_split_table_nothing_changes(self):
        prev = quarter(Q1, [row("CRWD", 100, 40000)])
        cur = quarter(Q2, [row("CRWD", 400, 40000)])
        build.diff(cur, prev)
        self.assertEqual(cur["rows"][0]["st"], "add")
        self.assertAlmostEqual(cur["rows"][0]["pct"], 300.0)


class TestRenames(unittest.TestCase):
    def _pair(self, slug):
        return whale(slug, [
            quarter(Q1, [row("881624209", 100, 1000, mapped=False, name="TEVA PHARMACEUTICAL INDS LTD"), row("AAPL", 10, 500)]),
            quarter(Q2, [row("TEVA", 101, 1100, name="Teva Pharmaceutical Industries"), row("AAPL", 10, 500)])])

    def test_two_whales_showing_the_same_swap(self):
        out = market.find_renames([self._pair("a"), self._pair("b")])
        self.assertEqual(out, {("TEVA", Q2): ("881624209", 2)})

    def test_one_whale_is_not_enough(self):
        self.assertEqual(market.find_renames([self._pair("a")]), {})

    def test_switching_between_funds_of_one_family(self):
        def sw(slug):
            return whale(slug, [quarter(Q1, [row("IWM", 100, 1000, name="ISHARES TR")]),
                                quarter(Q2, [row("FXI", 50, 900, name="ISHARES TR")])])
        self.assertEqual(market.find_renames([sw("a"), sw("b")]), {})


class TestStocks(unittest.TestCase):
    def setUp(self):
        self.a = whale("a", [quarter(Q1, [row("NVDA", 100, 1000), row("AAPL", 50, 500), row("GONE", 5, 50)]),
                             quarter(Q2, [row("NVDA", 150, 1800), row("AAPL", 50, 600)])])
        self.b = whale("b", [quarter(Q1, [row("NVDA", 10, 100)]),
                             quarter(Q2, [row("NVDA", 5, 60), row("NVDA", 7, 70, opt="PUT")])])
        self.old = whale("old", [quarter(Q1, [row("NVDA", 1, 10)])], status="ended")
        self.entries = [self.a, self.b, self.old]

    def test_holders_options_and_exits_are_kept_apart(self):
        stocks = market.collect_stocks(self.entries)
        nvda = stocks["NVDA"]
        self.assertEqual([h["m"]["slug"] for h in nvda["holders"]], ["a", "b"])   # 평가액 큰 순서, 공시 종료한 곳 제외
        self.assertEqual(nvda["value"], 1860)
        self.assertEqual(len(nvda["opts"]), 1)
        self.assertEqual([h["m"]["slug"] for h in stocks["GONE"]["exits"]], ["a"])
        self.assertEqual(stocks["GONE"]["holders"], [])

    def test_page_selection(self):
        stocks = market.collect_stocks(self.entries)
        self.assertEqual(market.pick_stocks(stocks, top_n=1, min_holders=2), {"NVDA"})
        self.assertIn("AAPL", market.pick_stocks(stocks, top_n=2, min_holders=3))

    def test_history_grid(self):
        hist = market.stock_history(self.entries, "GONE", ["2026-03-31", Q1, Q2])
        self.assertEqual(len(hist), 1)
        cells = hist[0]["cells"]
        self.assertIsNone(cells[0])                 # 그 분기 자료가 없다
        self.assertEqual(cells[1]["st"], "base")    # 첫 분기라 비교 대상이 없다
        self.assertEqual(cells[2]["st"], "exit")

    def test_quarter_summary_counts_only_meaningful_moves(self):
        c = whale("c", [quarter(Q1, [row("NVDA", 100, 1000), row("AAPL", 100, 1000)]),
                        quarter(Q2, [row("NVDA", 200, 2400), row("AAPL", 102, 1100)])])
        entries = [self.a, self.b, c] + [whale(f"x{i}", [quarter(Q1, [row("MSFT", 1, 10)]), quarter(Q2, [row("MSFT", 1, 10)])]) for i in range(3)]
        sm = market.quarter_summary(entries, Q2)
        self.assertEqual(len(sm["whales"]), 6)
        bought = {s["ticker"]: len(s["buy"]) for s in sm["bought"]}
        self.assertEqual(bought, {"NVDA": 2})       # a는 +50%, c는 +100%. b는 팔았다
        self.assertNotIn("AAPL", bought)            # c의 +2%는 세지 않는다
        self.assertEqual(sm["held"][0]["ticker"], "NVDA")
        # b가 판 NVDA 5주(추정 60)가 a의 GONE 청산(전분기 평가액 50)보다 크다.
        self.assertEqual([mv[2]["ticker"] for mv in sm["big_sells"]], ["NVDA", "GONE"])

    def test_too_few_whales_gives_no_summary(self):
        self.assertIsNone(market.quarter_summary([self.a, self.b], Q2))


class TestPreviewImage(unittest.TestCase):
    def test_png_is_well_formed(self):
        data = ogimage.card("Berkshire Hathaway Inc.", "13F PORTFOLIO 2026 Q3", [
            ("AAPL", "25.0%", "s-nt", 0, 0, 600, 384), ("BAC", "8.2%", "s-dn", 600, 0, 504, 384)])
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        w, h = struct.unpack(">II", data[16:24])
        self.assertEqual((w, h), (ogimage.W, ogimage.H))
        self.assertEqual(data[-8:-4], b"IEND")
        self.assertLess(len(data), 200_000)

    def test_only_drawable_characters_survive(self):
        self.assertEqual(ogimage.ascii_label("버크셔 Berkshire 한글"), "BERKSHIRE")
        self.assertEqual(ogimage.text_width("AB", 2), 22)
        self.assertEqual(ogimage.fit_scale("ABCDEFGHIJ", 100, 5), 1)
        self.assertEqual(ogimage.fit_scale("ABCDEFGHIJ", 10, 5), 0)

    def test_every_glyph_is_five_by_seven(self):
        for ch, rows in ogimage.FONT.items():
            self.assertEqual(len(rows), 7, ch)
            self.assertTrue(all(len(r) == 5 for r in rows), ch)


class TestUrls(unittest.TestCase):
    def test_stock_slug(self):
        self.assertEqual(build.stock_slug("BRK.B"), "brk-b")
        build.set_lang("ja")
        try:
            self.assertEqual(build.stock_url("NVDA"), "/ja/stocks/nvda/")
            self.assertEqual(build.quarter_url("2026-09-30"), "/ja/quarters/2026q3/")
        finally:
            build.set_lang("ko")

    def test_person_in_title(self):
        self.assertEqual(build.person_name({"ko": "x", "person": "워런 버핏 회장"}), "워런 버핏")
        self.assertEqual(build.person_name({"ko": "x", "person": "레이 달리오 창업"}), "")
        self.assertEqual(build.person_name({"ko": "x", "person": ""}), "")


if __name__ == "__main__":
    unittest.main()
