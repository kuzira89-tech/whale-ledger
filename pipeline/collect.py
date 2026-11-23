"""13F 수집 진입점 — managers.json의 모든 큰손을 돈다.

  python pipeline/collect.py                    # 전체, 최근 8분기
  python pipeline/collect.py --only berkshire   # 한 곳만
  python pipeline/collect.py --force            # 있는 분기도 다시 받기

분기 하나는 data/raw/<slug>/<period>/{holdings,meta}.json 으로 저장한다.
이미 받은 분기는 그 분기의 공시 목록(원본 + 정정)이 그대로면 건너뛴다.
정정 공시(13F-HR/A)가 새로 올라오면 목록이 달라지므로 그 분기만 다시 받는다.

SEC는 연락처가 든 User-Agent를 요구한다: 환경변수 EDGAR_USER_AGENT.
"""
from __future__ import annotations

import argparse
import json
import os

import edgar
import parse_13f

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")
SOURCE = "EDGAR 13F information table (data.sec.gov)"
SCHEMA = 2  # 스냅샷을 만드는 규칙이 바뀌면 올린다. 값이 다른 스냅샷은 다시 받는다.


def _json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_period(cik: int, group: list[edgar.Filing], period: str) -> list[parse_13f.RawHolding]:
    """한 분기의 원본과 정정 공시를 합쳐 최종 보유 내역을 만든다.

    group은 원본이 먼저, 정정이 제출일 순으로 뒤에 온다(edgar.group_by_period).
    정정에는 두 종류가 있다. RESTATEMENT는 전체를 다시 낸 것이라 통째로 바꾸고,
    NEW HOLDINGS는 비공개 승인이 풀린 종목을 추가하는 것이라 합친다. 종류는
    표지(primary_doc.xml)에 적혀 있다. 표지를 못 읽으면 규모로 판단한다:
    정정본이 원본의 절반보다 작으면 추가분으로 본다.
    """
    holdings: list[parse_13f.RawHolding] = []
    for f in group:
        rows = parse_13f.parse_info_table(edgar.fetch_info_table_xml(cik, f), period)
        if not f.form.endswith("/A"):
            if not holdings:          # 같은 분기에 원본이 둘이면 먼저 낸 것을 쓴다
                holdings = rows
            continue
        kind = edgar.fetch_amendment_type(cik, f)
        if not kind:
            kind = "NEW HOLDINGS" if holdings and len(rows) < len(holdings) / 2 else "RESTATEMENT"
        holdings = parse_13f.merge_amendment(holdings, rows, kind)
    return holdings


def normalize_units(holdings: list[parse_13f.RawHolding]) -> int:
    """평가액을 천 달러 단위로 적은 공시를 달러로 고친다. 곱한 배수(1 또는 1000)를 돌려준다.

    2023년부터 13F의 평가액은 달러 단위인데, 예전처럼 천 달러 단위로 내는 운용사가
    남아 있다(바우포스트, 듀케인). 그런 공시는 주당 가격(평가액 / 주식 수)이 실제의
    1/1000로 나온다. 주식 줄의 주당 가격 중앙값이 1달러에 못 미치면 천 달러 단위로 본다.
    """
    px = sorted(h.value / h.shares for h in holdings
                if h.share_type == "SH" and h.shares > 0 and h.value > 0)
    if not px:
        return 1
    thousands = px[len(px) // 2] < 1.0 if len(px) >= 3 else max(px) < 1.0
    if not thousands:
        return 1
    for h in holdings:
        h.value *= 1000
    return 1000


def to_row(h: parse_13f.RawHolding, tmap: dict) -> list:
    ent = tmap.get(h.cusip.upper(), {})
    ticker = ent.get("ticker") or h.cusip.upper()
    if h.put_call:  # 옵션은 주식과 다른 줄로 남긴다
        ticker = f"{ticker} ({h.put_call})"
    return [ticker, ent.get("name") or h.name, ent.get("cl", ""), h.shares, h.value, h.cusip.upper()]


def plan_periods(m: dict) -> dict[str, tuple[int, str, list[edgar.Filing]]]:
    """분기 -> (CIK, SEC 등록명, 그 분기의 공시들).

    보통은 CIK 하나다. 공시 주체가 중간에 바뀐 곳은 managers.json에
    "sources": [{"cik": ..., "from": "2026-06-30"}, {"cik": ..., "until": "2026-03-31"}]
    처럼 적는다. 한 분기는 먼저 적힌 source 것을 쓴다.
    """
    slug = m["slug"]
    sources = m.get("sources") or [{"cik": m["cik"]}]
    out: dict[str, tuple[int, str, list[edgar.Filing]]] = {}
    for s in sources:
        cik = int(s["cik"])
        name, filings = edgar.list_13f_filings_with_name(cik)
        want = (s.get("expect") or m.get("expect") or "").upper()
        if want and want not in name.upper():
            print(f"  ! {slug}: CIK {cik}의 SEC 등록명이 '{name}'입니다. '{want}'가 들어 있지 않아 건너뜁니다.")
            continue
        for period, group in edgar.group_by_period(filings).items():
            if s.get("from") and period < s["from"]:
                continue
            if s.get("until") and period > s["until"]:
                continue
            out.setdefault(period, (cik, name, group))
    return out


def collect_manager(m: dict, tmap: dict, quarters: int, force: bool) -> int:
    slug = m["slug"]
    by_period = plan_periods(m)
    written = 0
    for period in sorted(by_period, reverse=True)[:quarters]:
        cik, name, group = by_period[period]
        accessions = [f.accession for f in group]
        pdir = os.path.join(RAW_DIR, slug, period)
        old = _json(os.path.join(pdir, "meta.json"), {})
        if not force and old.get("accessions") == accessions and old.get("schema") == SCHEMA:
            continue
        try:
            holdings = build_period(cik, group, period)
        except Exception as ex:  # 한 분기가 실패해도 나머지는 계속한다
            print(f"  ! {slug} {period}: 받지 못했습니다 ({ex}). 기존 자료는 그대로 둡니다.")
            continue
        if not holdings or parse_13f.total_value(holdings) <= 0:
            print(f"  ! {slug} {period}: 보유 내역이 비었거나 평가액 합계가 0이라 저장하지 않았습니다 "
                  f"({len(holdings)}행, 공시 {', '.join(f.form + ' ' + f.accession for f in group)}).")
            continue
        scale = normalize_units(holdings) if parse_13f.value_multiplier_for_period(period) == 1 else 1
        if scale != 1:
            print(f"  {slug} {period}: 평가액이 천 달러 단위로 적혀 있어 {scale}을 곱했습니다.")
        rows = sorted((to_row(h, tmap) for h in holdings), key=lambda r: -r[4])
        originals = [f for f in group if not f.form.endswith("/A")]
        first = (originals or group)[0]
        meta = {
            "period": period,
            "filed": first.filing_date,
            "form": first.form,
            "accession": first.accession,
            "accessions": accessions,
            "amended": max((f.filing_date for f in group if f.form.endswith("/A")), default=""),
            "total_value": parse_13f.total_value(holdings),
            "num_holdings": len(holdings),
            "entity": name,
            "cik": cik,
            "unit_scale": scale,
            "schema": SCHEMA,
            "source": SOURCE,
        }
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "holdings.json"), "w", encoding="utf-8") as f:
            json.dump({"period": period, "holdings": rows}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(pdir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        written += 1
        print(f"  {slug} {period}: {len(rows)}종목  [{len(group)}건 공시]")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="managers.json의 큰손들 13F를 EDGAR에서 받는다")
    ap.add_argument("--only", help="이 slug만")
    ap.add_argument("--quarters", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    managers = _json(os.path.join(ROOT, "managers.json"), [])
    tmap = _json(os.path.join(HERE, "ticker_map.json"), {}).get("by_cusip", {})
    total = 0
    for m in managers:
        if args.only and m["slug"] != args.only:
            continue
        try:
            total += collect_manager(m, tmap, args.quarters, args.force)
        except Exception as ex:  # 한 곳이 실패해도 나머지는 계속한다
            print(f"  ! {m['slug']}: EDGAR 조회 실패 ({ex})")
    print(f"저장한 분기: {total}")


if __name__ == "__main__":
    main()
