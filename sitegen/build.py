#!/usr/bin/env python3
"""정적 사이트 생성기.

data/raw/<slug>/<period>/{holdings,meta}.json 스냅샷을 읽어 site/ 아래에
완성된 HTML을 만든다. 브라우저에서 도는 스크립트는 없다. 차트는 전부
빌드할 때 계산한 CSS 상자다. 표준 라이브러리만 쓴다.

한국어판은 사이트 뿌리(/)에, 일본어판은 /ja/ 아래에 같은 구조로 만든다.

  /                     큰손 목록과 이번 분기 요약
  /whales/<slug>/       큰손 한 곳(최신 분기), /whales/<slug>/2026q2/ 는 지난 분기
  /stocks/<ticker>/     종목 하나를 누가 들고 있는지, /stocks/ 는 종목 목록
  /quarters/2026q3/     한 분기에 큰손들이 함께 사고판 종목
  /guide/               13F 읽는 법과 이 사이트의 계산 방식

  python sitegen/build.py            # site/ 전체 생성
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market   # noqa: E402
import ogimage  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
SITE = os.path.join(ROOT, "site")
SITE_URL = "https://whaleportfolio.com"   # 대표 주소. www로 들어와도 검색엔진에는 이 주소를 알린다.
# 예전 사이트(ChatGPT Sites 시절)의 주소. 북마크나 검색으로 들어오면 홈으로 보낸다.
OLD_PATHS = ("/dashboard", "/portfolio", "/consensus", "/advertising")
MINUS = "−"
MAX_TABLE_ROWS = 100
MAX_MOVES = 10
MAX_RANK = 10          # 분기 요약의 순위 길이
HIST_QUARTERS = 8      # 분기별 흐름에 보여 줄 분기 수
INDEX_ROWS = 200       # 종목 목록에서 표로 보여 줄 줄 수

# main()이 채운다. 페이지를 만드는 함수들이 읽기만 한다.
SPLITS: dict[tuple[str, str], float] = {}     # 확인된 주식 분할 (티커, 분기) → 비율
SUSPECTS: dict[tuple[str, str], float] = {}   # 분할로 보이지만 확인하지 못한 것
RENAMES: dict[tuple[str, str], tuple] = {}    # 식별 번호가 바뀐 것으로 보이는 (새 티커, 분기)
STOCK_PAGES: set[str] = set()                 # 전용 페이지가 있는 티커
NEWEST = ""                                   # 가장 많은 큰손이 공시한 최신 분기
QUARTER_PAGES: list[str] = []                 # 요약 페이지가 있는 분기(오래된 것부터)
SUMMARIES: dict[str, dict] = {}               # 분기 → market.quarter_summary() 결과

LANGS = ("ko", "ja")
PREFIX = {"ko": "", "ja": "/ja"}       # 언어별 주소 앞부분
LANG_LABEL = {"ko": "한국어", "ja": "日本語"}

T = {
    "ko": {
        "site": "큰손 포트폴리오", "nav": "큰손", "lang_aria": "언어",
        "footer": "출처는 미국 SEC EDGAR의 Form 13F-HR입니다. 13F에는 분기 말 미국 상장 주식 보유분만 들어가고, 공매도와 현금, 대부분의 해외 주식은 빠집니다. 공시는 분기가 끝나고 최대 45일 뒤에 나옵니다. 투자 권유가 아닙니다.",
        "privacy": "개인정보 처리방침",
        "as_of": "기준일", "filed": "공시일", "temp_src": "임시 데이터(2차 집계 출처)",
        "stat_total": "공시 총액", "stat_count": "보유 종목", "stat_top10": "상위 10개 비중", "stat_qoq": "전분기 대비",
        "buys": "늘림", "sells": "줄임", "none": "이번 분기에는 없습니다.", "est": "추정",
        "moves_more": "금액이 작은 {n}건은 여기에 싣지 않았습니다.",
        "est_note": "금액은 주식 수 변화에 분기 말 가격을 곱한 추정치입니다. 청산은 전분기 말 평가액입니다.",
        "map": "포트폴리오 지도", "lg_up": "늘림", "lg_dn": "줄임", "lg_nt": "그대로",
        "cap": "면적은 비중, 색은 이번 분기 주식 수 변화입니다.",
        "cap_noprev": "면적은 비중입니다. 직전 분기 자료가 없어 변화는 색으로 표시하지 않았습니다.",
        "noprev": "직전 분기({q}) 자료가 없어 이번 분기에 무엇을 사고팔았는지는 계산하지 않았습니다.",
        "rest_note": "비중이 작은 {n}개 종목은 \"기타\"로 묶었습니다. 전체는 아래 표에 있습니다.",
        "etc_n": "기타 {n}개", "etc": "기타", "sum": "합계",
        "ended": "공시 종료", "note": "알아둘 점",
        "hist": "분기별 흐름", "hist_cap": "공시 총액과 종목 수입니다. 막대를 누르면 그 분기로 갑니다.",
        "no_data": "자료 없음", "count": "{n}개",
        "holdings": "보유 종목", "th": ("종목", "비중", "평가액", "보유 주식 수", "이번 분기"),
        "more_rows": "나머지 {n}개 종목 펼치기 · 합계 {p}%",
        "capped": "비중이 큰 {m}개까지만 표시했습니다. 전체는 {n}개입니다.",
        "sec": "SEC 원문 보기", "accession": "접수번호", "prev_q": "이전 분기", "next_q": "다음 분기",
        "st": {"new": "신규", "exit": "청산", "keep": "유지"},
        "kind": {"new": "신규", "add": "확대", "trim": "축소", "exit": "청산"},
        "opt": {"PUT": " 풋", "CALL": " 콜"}, "lt01": "0.1% 미만",
        "page_title": "{name} 포트폴리오 {q} | {site}",
        "page_desc": "{name}의 {q} 13F 공시. 공시 총액 {total}, 보유 종목 {n}개.",
        "home_h1": "큰손들은 이번 분기에<br>무엇을 사고팔았나",
        "home_meta": "분기 말 보유 내역을 직전 분기와 비교해 큰손별로 정리했습니다.",
        "home_cols": ("큰손", "공시 총액", "종목 수", "최대 보유", "이번 분기 주요 움직임"),
        "basis": "{q} 기준", "waiting": "첫 수집을 기다리는 곳 {n}곳: ", "empty": "아직 수집된 분기가 없습니다",
        "home_title": "큰손 포트폴리오 — 13F로 보는 큰손들의 분기별 매매",
        "home_desc": "미국 SEC 13F 공시로 큰손들이 분기마다 무엇을 사고팔았는지 큰손별로 정리합니다.",
        "nav_whales": "큰손", "nav_stocks": "종목", "nav_quarter": "분기 요약", "nav_guide": "13F 안내", "nav_aria": "주 메뉴",
        "page_title_p": "{name}({person}) 포트폴리오 {q} | {site}",
        "page_desc_p": "{person}의 {name} {q} 13F 공시. 공시 총액 {total}, 보유 종목 {n}개.",
        "split_note": "주식 분할을 반영한 종목: {list}. 분할 전 주식 수에 분할 비율을 곱해 비교했습니다.",
        "n_whales": "{n}곳", "rank": "{n}위",
        "stocks": "종목", "st_holders": "보유한 큰손", "st_of": "추적 {n}곳 중", "st_value": "합계 평가액",
        "st_up": "늘린 곳", "st_dn": "줄인 곳", "st_new": "신규 {n}", "st_exit": "청산 {n}",
        "st_who": "누가 들고 있나", "st_who_cap": "{q} 말 기준입니다. 비중은 각 큰손의 포트폴리오에서 이 종목이 차지하는 몫입니다.",
        "st_th": ("큰손", "포트폴리오 내 비중", "평가액", "보유 주식 수", "이번 분기"),
        "st_exits": "이번 분기에 전부 판 곳",
        "st_opts": "옵션 포지션", "st_opts_cap": "풋·콜은 기초자산의 명목 금액으로 공시됩니다. 위 합계에는 넣지 않았습니다.",
        "st_hist": "분기별 움직임", "st_hist_cap": "숫자는 그 분기의 주식 수 변화입니다. 빈칸은 보유하지 않은 분기, 줄표는 자료가 없는 분기입니다.",
        "cell": {"base": "보유", "keep": "유지", "new": "신규", "exit": "청산"},
        "st_count_row": "보유한 곳",
        "st_none": "지금은 추적 대상 가운데 이 종목을 보유한 곳이 없습니다.",
        "stock_title": "{name}({tk}) 보유 큰손 {q} | {site}",
        "stock_desc": "{tk} {name} — 보유한 큰손 {n}곳. {q}에 늘린 곳 {b}곳, 줄인 곳 {s}곳. 13F 공시 기준.",
        "stocks_h1": "종목으로 보기",
        "stocks_meta": "세 곳 이상이 들고 있거나 어느 한 곳의 상위 25위 안에 드는 종목 {n}개입니다. {q} 기준.",
        "stocks_cols": ("종목", "보유한 큰손", "합계 평가액", "이번 분기"),
        "stocks_title": "큰손들이 보유한 종목 {q} | {site}",
        "stocks_desc": "13F 공시로 본 큰손 보유 종목 {n}개. 보유한 큰손이 많은 순서로 정리했습니다. {q} 기준.",
        "stocks_more": "그 밖의 종목", "moved": "늘림 {b} · 줄임 {s}",
        "q_title": "{q} 큰손 매매 요약 | {site}",
        "q_desc": "{q}에 큰손 {n}곳이 함께 사고판 종목. 가장 많은 곳이 산 종목은 {a}, 가장 많은 곳이 판 종목은 {b}.",
        "q_h1": "{q}에 큰손들이<br>함께 사고판 종목",
        "q_meta": "직전 분기와 비교할 수 있는 {n}곳을 모았습니다. 주식 수를 5% 이상 바꾼 경우만 셉니다.",
        "q_bought": "여러 곳이 산 종목", "q_sold": "여러 곳이 판 종목",
        "q_bigbuy": "금액이 큰 매수", "q_bigsell": "금액이 큰 매도", "q_big": "금액이 큰 거래",
        "q_held": "가장 널리 보유한 종목", "q_held_cap": "분기 말에 이 종목을 들고 있던 큰손 수와 평가액 합계입니다.",
        "q_more": "외 {n}곳", "q_none": "해당하는 종목이 없습니다.", "q_other": "다른 분기",
        "q_suspect": "주식 분할이나 종목 코드 변경으로 보이지만 아직 확인하지 못한 종목은 순위에서 뺐습니다: {list}",
        "home_q": "{q} 한눈에", "home_q_more": "분기 요약 전체 보기",
        "guide_title": "13F 읽는 법 | {site}",
        "guide_desc": "13F 공시가 무엇이고 무엇이 빠지는지, 이 사이트가 늘림·줄임과 추정 금액을 어떻게 계산하는지 정리했습니다.",
        "guide_whales": "추적 대상",
    },
    "ja": {
        "site": "クジラ・ポートフォリオ", "nav": "大口投資家", "lang_aria": "言語",
        "footer": "出典は米国SEC EDGARのForm 13F-HRです。13Fには四半期末時点の米国上場株式の保有分だけが載り、空売り・現金・大半の海外株式は含まれません。開示は四半期末から最大45日後です。投資勧誘ではありません。",
        "privacy": "プライバシーポリシー",
        "as_of": "基準日", "filed": "開示日", "temp_src": "暫定データ(二次集計)",
        "stat_total": "開示総額", "stat_count": "保有銘柄", "stat_top10": "上位10銘柄の比率", "stat_qoq": "前四半期比",
        "buys": "買い増し", "sells": "売り", "none": "今四半期はありません。", "est": "推定",
        "moves_more": "金額の小さい{n}件は省略しました。",
        "est_note": "金額は株数の変化に四半期末の株価を掛けた推定値です。全売却は前四半期末の評価額です。",
        "map": "ポートフォリオ・マップ", "lg_up": "買い増し", "lg_dn": "売り", "lg_nt": "変わらず",
        "cap": "面積は比率、色は今四半期の株数の変化です。",
        "cap_noprev": "面積は比率です。前四半期のデータがないため、変化は色で示していません。",
        "noprev": "前四半期({q})のデータがないため、今四半期の売買は計算していません。",
        "rest_note": "比率の小さい{n}銘柄は「その他」にまとめました。全体は下の表にあります。",
        "etc_n": "その他 {n}銘柄", "etc": "その他", "sum": "合計",
        "ended": "開示終了", "note": "注記",
        "hist": "四半期ごとの推移", "hist_cap": "開示総額と銘柄数です。棒を押すとその四半期に移動します。",
        "no_data": "データなし", "count": "{n}銘柄",
        "holdings": "保有銘柄", "th": ("銘柄", "比率", "評価額", "保有株数", "今四半期"),
        "more_rows": "残り{n}銘柄を表示 · 合計 {p}%",
        "capped": "比率の大きい{m}銘柄まで表示しています。全体は{n}銘柄です。",
        "sec": "SEC原文を見る", "accession": "受付番号", "prev_q": "前の四半期", "next_q": "次の四半期",
        "st": {"new": "新規", "exit": "全売却", "keep": "維持"},
        "kind": {"new": "新規", "add": "買い増し", "trim": "削減", "exit": "全売却"},
        "opt": {"PUT": " プット", "CALL": " コール"}, "lt01": "0.1%未満",
        "page_title": "{name} ポートフォリオ {q} | {site}",
        "page_desc": "{name}の{q} 13F開示。開示総額 {total}、保有銘柄 {n}。",
        "home_h1": "大口投資家は今四半期に<br>何を売買したか",
        "home_meta": "四半期末の保有状況を前四半期と比べ、投資家ごとにまとめました。",
        "home_cols": ("大口投資家", "開示総額", "銘柄数", "最大保有", "今四半期の主な動き"),
        "basis": "{q} 時点", "waiting": "初回の収集待ち {n}件: ", "empty": "まだ収集された四半期がありません",
        "home_title": "クジラ・ポートフォリオ — 13Fで見る大口投資家の四半期売買",
        "home_desc": "米国SECの13F開示から、大口投資家が四半期ごとに何を売買したかを投資家別にまとめます。",
        "nav_whales": "大口投資家", "nav_stocks": "銘柄", "nav_quarter": "四半期まとめ", "nav_guide": "13Fの読み方", "nav_aria": "メインメニュー",
        "page_title_p": "{name}({person}) ポートフォリオ {q} | {site}",
        "page_desc_p": "{person}の{name}、{q} 13F開示。開示総額 {total}、保有銘柄 {n}。",
        "split_note": "株式分割を反映した銘柄: {list}。分割前の株数に分割比率を掛けて比べています。",
        "n_whales": "{n}社", "rank": "{n}位",
        "stocks": "銘柄", "st_holders": "保有する投資家", "st_of": "追跡{n}社のうち", "st_value": "評価額の合計",
        "st_up": "買い増し", "st_dn": "売り", "st_new": "新規 {n}", "st_exit": "全売却 {n}",
        "st_who": "誰が保有しているか", "st_who_cap": "{q}末時点です。比率は各投資家のポートフォリオに占めるこの銘柄の割合です。",
        "st_th": ("大口投資家", "ポートフォリオ内の比率", "評価額", "保有株数", "今四半期"),
        "st_exits": "今四半期にすべて売却した投資家",
        "st_opts": "オプション・ポジション", "st_opts_cap": "プット・コールは原資産の想定元本で開示されます。上の合計には含めていません。",
        "st_hist": "四半期ごとの動き", "st_hist_cap": "数字はその四半期の株数の変化です。空欄は保有していない四半期、ダッシュはデータのない四半期です。",
        "cell": {"base": "保有", "keep": "維持", "new": "新規", "exit": "全売却"},
        "st_count_row": "保有社数",
        "st_none": "現在、追跡対象の中にこの銘柄を保有する投資家はいません。",
        "stock_title": "{name}({tk})を保有する大口投資家 {q} | {site}",
        "stock_desc": "{tk} {name} — 保有する大口投資家は{n}社。{q}に買い増し{b}社、売り{s}社。13F開示ベース。",
        "stocks_h1": "銘柄から見る",
        "stocks_meta": "3社以上が保有しているか、いずれかの投資家の上位25位に入る{n}銘柄です。{q} 時点。",
        "stocks_cols": ("銘柄", "保有する投資家", "評価額の合計", "今四半期"),
        "stocks_title": "大口投資家が保有する銘柄 {q} | {site}",
        "stocks_desc": "13F開示から見た大口投資家の保有{n}銘柄。保有する投資家の多い順にまとめました。{q} 時点。",
        "stocks_more": "そのほかの銘柄", "moved": "買い増し {b} · 売り {s}",
        "q_title": "{q} 大口投資家の売買まとめ | {site}",
        "q_desc": "{q}に大口投資家{n}社がそろって売買した銘柄。最も多くの投資家が買ったのは{a}、売ったのは{b}。",
        "q_h1": "{q}に大口投資家が<br>そろって売買した銘柄",
        "q_meta": "前四半期と比べられる{n}社を集計しました。株数を5%以上変えた場合だけを数えています。",
        "q_bought": "複数の投資家が買った銘柄", "q_sold": "複数の投資家が売った銘柄",
        "q_bigbuy": "金額の大きい買い", "q_bigsell": "金額の大きい売り", "q_big": "金額の大きい売買",
        "q_held": "最も広く保有されている銘柄", "q_held_cap": "四半期末にこの銘柄を保有していた投資家の数と評価額の合計です。",
        "q_more": "ほか{n}社", "q_none": "該当する銘柄はありません。", "q_other": "ほかの四半期",
        "q_suspect": "株式分割や銘柄コードの変更とみられるものの未確認の銘柄は順位から除きました: {list}",
        "home_q": "{q} のまとめ", "home_q_more": "四半期まとめをすべて見る",
        "guide_title": "13Fの読み方 | {site}",
        "guide_desc": "13F開示とは何か、何が含まれないのか、このサイトが買い増し・売りと推定金額をどう計算しているかをまとめました。",
        "guide_whales": "追跡対象",
    },
}

# 지금 만들고 있는 언어. main()이 언어를 바꿔 가며 페이지를 만든다.
LANG = "ko"
L = T["ko"]
NAMES: dict[str, dict] = {"ko": {}, "ja": {}}

e = html.escape


def set_lang(lang: str) -> None:
    global LANG, L
    LANG, L = lang, T[lang]


def mfield(m: dict, key: str) -> str:
    """큰손 정보에서 지금 언어의 값을 꺼낸다. 이름은 ko/ja, 나머지는 key_ja 식이다."""
    if key == "name":
        return m.get(LANG) or m.get("en") or m["ko"]
    if LANG == "ko":
        return m.get(key, "")
    return m.get(f"{key}_{LANG}") or m.get(key, "")


# ------------------------------------------------------------------ 불러오기

def _json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_cusip(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{9}", s)) and any(c.isdigit() for c in s)


def load_tmap() -> dict:
    """CUSIP → {ticker, name?, cl?}. OpenFIGI로 찾은 것 위에 손으로 관리하는 표를 덮어쓴다."""
    figi = _json(os.path.join(ROOT, "pipeline", "figi_cache.json"), {})
    tmap = {c: {"ticker": v["ticker"]} for c, v in figi.items() if v.get("ticker")}
    tmap.update(_json(os.path.join(ROOT, "pipeline", "ticker_map.json"), {}).get("by_cusip", {}))
    return tmap


def load_quarter(slug: str, period: str, tmap: dict) -> dict:
    """스냅샷 한 분기를 읽는다. 행은 [티커, 이름, 종류, 주식 수, 평가액(, CUSIP)].

    티커 자리에 CUSIP이 그대로 든 행이 섞여 있다. 같은 종목이 분기마다 다른 키로
    잡히면 신규·청산으로 잘못 보이므로 여기서 통일한다.
    """
    pdir = os.path.join(RAW, slug, period)
    rows_in = _json(os.path.join(pdir, "holdings.json"), {}).get("holdings", [])
    meta = _json(os.path.join(pdir, "meta.json"), {})
    agg: dict[str, dict] = {}
    for row in rows_in:
        tk, name, cl, shares, value = (list(row) + ["", "", "", 0, 0])[:5]
        opt = ""
        m = re.match(r"^(.*) \((PUT|CALL)\)$", tk)
        if m:
            tk, opt = m.group(1), m.group(2)
        cusip = row[5] if len(row) > 5 else (tk if is_cusip(tk) else "")
        ent = tmap.get(tk) if is_cusip(tk) else None
        if ent:
            tk, name, cl = ent["ticker"], ent.get("name") or name, ent.get("cl", "")
        key = tk + (":" + opt if opt else "")
        if key in agg:
            agg[key]["shares"] += int(shares)
            agg[key]["value"] += int(value)
        else:
            agg[key] = {"key": key, "ticker": tk, "name": name, "cl": cl, "opt": opt,
                        "cusip": cusip, "mapped": not is_cusip(tk),
                        "shares": int(shares), "value": int(value)}
    rows = sorted(agg.values(), key=lambda r: -r["value"])
    total = sum(r["value"] for r in rows) or 1
    for r in rows:
        r["w"] = r["value"] / total * 100
    return {"period": period, "meta": meta, "rows": rows, "total": total}


def load_manager(m: dict, tmap: dict) -> list[dict]:
    mdir = os.path.join(RAW, m["slug"])
    if not os.path.isdir(mdir):
        return []
    periods = sorted(d for d in os.listdir(mdir)
                     if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)
                     and os.path.exists(os.path.join(mdir, d, "holdings.json")))
    quarters = [load_quarter(m["slug"], p, tmap) for p in periods]
    # 평가액 합계가 0인 스냅샷은 쓸 수 없는 자료다(비중을 계산할 수 없다).
    return [q for q in quarters if q["rows"] and sum(r["value"] for r in q["rows"]) > 0]


# ------------------------------------------------------------------ 분기 계산

Q_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def q_of(period: str) -> tuple[int, int]:
    y, m, _ = period.split("-")
    return int(y), (int(m) + 2) // 3


def qlabel(period: str) -> str:
    y, q = q_of(period)
    return f"{y} Q{q}"


def qshort(period: str) -> str:
    y, q = q_of(period)
    return f"{y % 100:02d} Q{q}"


def qslug(period: str) -> str:
    y, q = q_of(period)
    return f"{y}q{q}"


def prev_period(period: str) -> str:
    y, q = q_of(period)
    y, q = (y - 1, 4) if q == 1 else (y, q - 1)
    return f"{y}-{Q_END[q]}"


def dot(d: str) -> str:
    return d.replace("-", ".") if d else ""


def diff(cur: dict, prev: dict | None, splits: dict | None = None) -> dict | None:
    """직전 분기와 비교해 cur의 각 행에 상태를 붙이고, 움직임 요약을 돌려준다.

    추정 금액은 주식 수 변화에 이번 분기 말 가격(평가액 / 주식 수)을 곱한 값이다.
    청산은 전분기 말 평가액을 쓴다. 13F에는 실제 거래 가격이 없다.

    splits는 {(티커, 분기): 비율}이다. 그 분기에 주식 분할이 있었던 종목은 직전 분기
    주식 수에 비율을 곱한 뒤 비교한다. 그러지 않으면 보유자 전원이 산 것처럼 보인다.
    """
    if prev is None:
        for r in cur["rows"]:
            r.update(st="base", pct=None, d=0, est=0)
        return None
    pb = {r["key"]: r for r in prev["rows"]}
    buys, sells, adjusted = [], [], {}
    for r in cur["rows"]:
        p = pb.get(r["key"])
        px = r["value"] / r["shares"] if r["shares"] else 0
        if p is None:
            r.update(st="new", pct=None, d=r["shares"], est=r["value"])
            buys.append(r)
            continue
        base = p["shares"]
        k = (splits or {}).get((r["ticker"], cur["period"]))
        if k:
            base = round(base * k)
            adjusted[r["ticker"]] = k
        d = r["shares"] - base
        if k and abs(d) <= max(1, base * 0.0005):
            d = 0          # 분할 때 생기는 단주 처리 정도의 차이는 매매로 보지 않는다
        if d == 0:
            r.update(st="keep", pct=0.0, d=0, est=0)
            continue
        r.update(st="add" if d > 0 else "trim",
                 pct=(d / base * 100 if base else None),
                 d=d, est=abs(d) * px)
        (buys if d > 0 else sells).append(r)
    held = {r["key"] for r in cur["rows"]}
    exits = [dict(p, st="exit", pct=-100.0, d=-p["shares"], est=p["value"], w=0.0)
             for k, p in pb.items() if k not in held]
    sells = sells + exits
    buys.sort(key=lambda r: -r["est"])
    sells.sort(key=lambda r: -r["est"])
    return {
        "buys": buys, "sells": sells,
        "n_new": sum(r["st"] == "new" for r in buys),
        "n_add": sum(r["st"] == "add" for r in buys),
        "n_trim": sum(r["st"] == "trim" for r in sells),
        "n_exit": len(exits),
        "buy_total": sum(r["est"] for r in buys),
        "sell_total": sum(r["est"] for r in sells),
        "total_chg": (cur["total"] / prev["total"] - 1) * 100,
        "prev_total": prev["total"],
        "splits": adjusted,
    }


def squarify(items: list[tuple], w: float, h: float) -> list[tuple]:
    """정사각형에 가깝게 채우는 트리맵 배치. items는 면적 내림차순 (obj, area)."""
    total = sum(a for _, a in items) or 1
    scale = w * h / total
    items = [(o, a * scale) for o, a in items if a > 0]
    out, x, y = [], 0.0, 0.0

    def worst(row, side):
        s = sum(a for _, a in row)
        return max(side * side * max(a for _, a in row) / (s * s),
                   s * s / (side * side * min(a for _, a in row)))

    while items:
        side = min(w, h)
        row, i = [items[0]], 1
        while i < len(items) and worst(row + [items[i]], side) <= worst(row, side):
            row.append(items[i])
            i += 1
        s = sum(a for _, a in row)
        if w >= h:
            rw, yy = s / h, y
            for o, a in row:
                out.append((o, x, yy, rw, a / rw))
                yy += a / rw
            x, w = x + rw, w - rw
        else:
            rh, xx = s / w, x
            for o, a in row:
                out.append((o, xx, y, a / rh, rh))
                xx += a / rh
            y, h = y + rh, h - rh
        items = items[i:]
    return out


# ------------------------------------------------------------------ 표기

def usd_head(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"${a / 1e9:.2f}B"
    return f"${a / 1e6:.1f}M"


def usd_tbl(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"${a / 1e9:.1f}B"
    if a >= 1e7:
        return f"${a / 1e6:.0f}M"
    if a >= 1e6:
        return f"${a / 1e6:.1f}M"
    return f"${a / 1e3:.0f}K"


def usd_est(v: float, sign: str) -> str:
    a = abs(v)
    if a >= 1e9:
        s = f"${a / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"${a / 1e6:.1f}M"
    else:
        s = f"${a / 1e3:.0f}K"
    return sign + s


def pct_txt(r: dict) -> str:
    if r["st"] in L["st"]:
        return L["st"][r["st"]]
    if r["st"] == "base" or r["pct"] is None:
        return "—"
    p = r["pct"]
    if abs(p) < 0.05:
        return "≈0%"
    if abs(p) >= 1000:
        return f"{'+' if p > 0 else MINUS}{abs(p):,.0f}%"
    return f"{'+' if p > 0 else MINUS}{abs(p):.1f}%"


def tone(r: dict) -> str:
    return {"new": "up", "add": "up", "trim": "dn", "exit": "dn"}.get(r["st"], "nt")


def tk_txt(r: dict) -> str:
    """티커 자리에 쓸 짧은 이름. 티커를 모르면 발행사 이름 앞부분을 쓴다."""
    base = r["ticker"] if r["mapped"] else nice(r["name"])[:18]
    return base + L["opt"].get(r["opt"], "")


def nice(name: str) -> str:
    return name.title() if name.isupper() else name


def name_txt(r: dict) -> str:
    if r["mapped"]:
        return NAMES[LANG].get(r["ticker"]) or nice(r["name"])
    return f"CUSIP {r['cusip'] or r['ticker']}"


def w_txt(w: float) -> str:
    return L["lt01"] if 0 < w < 0.05 else f"{w:.1f}%"


def whale_url(m: dict, period: str, latest: str, lang: str | None = None) -> str:
    base = f"{PREFIX[lang or LANG]}/whales/{m['slug']}/"
    return base if period == latest else f"{base}{qslug(period)}/"


def stock_slug(ticker: str) -> str:
    return ticker.lower().replace(".", "-")


def stock_url(ticker: str, lang: str | None = None) -> str:
    return f"{PREFIX[lang or LANG]}/stocks/{stock_slug(ticker)}/"


def quarter_url(period: str, lang: str | None = None) -> str:
    return f"{PREFIX[lang or LANG]}/quarters/{qslug(period)}/"


def tk_link(r: dict) -> str:
    """티커 글자. 전용 페이지가 있는 종목이면 그 페이지로 잇는다."""
    txt = e(tk_txt(r))
    if r["mapped"] and r["ticker"] in STOCK_PAGES:
        return f'<a href="{stock_url(r["ticker"])}">{txt}</a>'
    return txt


def person_name(m: dict) -> str:
    """제목에 넣을 인물 이름. "창업"처럼 지금은 손을 뗀 사람이라는 표시가 붙은 곳은 뺀다."""
    p = mfield(m, "person")
    if not p or re.search(r"(창업|創業)$", p):
        return ""
    return re.sub(r"\s*(회장|会長)$", "", p)


def og_path(name: str) -> str:
    return f"/assets/og/{name}.png"


# ------------------------------------------------------------------ 조각

LOCALE = {"ko": "ko_KR", "ja": "ja_JP"}


def page(title: str, desc: str, body: str, paths: dict[str, str],
         section: str = "", og: str = "") -> str:
    """paths: 언어 → 이 페이지의 그 언어 주소. 대표 주소와 언어 전환 링크에 쓴다.

    section은 머리말 메뉴에서 지금 있는 곳, og는 공유 미리보기 그림의 주소다.
    """
    alts = "".join(f'<link rel="alternate" hreflang="{lg}" href="{SITE_URL}{p}">\n' for lg, p in paths.items())
    alts += f'<link rel="alternate" hreflang="x-default" href="{SITE_URL}{paths["ko"]}">\n'
    here = ' aria-current="true"'
    switch = "".join(
        f'<a href="{p}" lang="{lg}" hreflang="{lg}"{here if lg == LANG else ""}>{LANG_LABEL[lg]}</a>'
        for lg, p in paths.items())
    home = PREFIX[LANG] + "/"
    items = [("whales", home, L["nav_whales"]), ("stocks", PREFIX[LANG] + "/stocks/", L["nav_stocks"])]
    if QUARTER_PAGES:
        items.append(("quarters", quarter_url(QUARTER_PAGES[-1]), L["nav_quarter"]))
    items.append(("guide", PREFIX[LANG] + "/guide/", L["nav_guide"]))
    nav = "".join(f'<a href="{u}"{here if k == section else ""}>{t}</a>' for k, u, t in items)
    image = SITE_URL + (og or og_path(f"site-{qslug(NEWEST)}" if NEWEST else "site"))
    plain = re.sub(r"<[^>]+>", " ", title)
    return f"""<!doctype html>
<html lang="{LANG}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(plain)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE_URL}{paths[LANG]}">
{alts}<meta property="og:type" content="website">
<meta property="og:site_name" content="{L['site']}">
<meta property="og:title" content="{e(plain)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{SITE_URL}{paths[LANG]}">
<meta property="og:locale" content="{LOCALE[LANG]}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="{ogimage.W}">
<meta property="og:image:height" content="{ogimage.H}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&amp;display=swap">
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{home}">{L['site']}</a>
<nav aria-label="{L['nav_aria']}">{nav}</nav>
<div class="langs" aria-label="{L['lang_aria']}">{switch}</div>
</div></header>
<main class="wrap">
{body}
<footer>
<p>{L['footer']}</p>
<a href="/privacy">{L['privacy']}</a>
</footer>
</main>
</body>
</html>
"""


def treemap_layout(rows: list[dict], W: float, H: float) -> tuple[list[tuple], list[dict], float]:
    """트리맵 배치. (칸 목록, "기타"로 묶인 행, 기타의 비중)을 돌려준다. 칸의 행이 None이면 기타다."""
    main = [r for r in rows if r["w"] >= 0.45][:30]
    rest = rows[len(main):]
    rest_share = sum(r["w"] for r in rest)
    items = [(r, r["value"]) for r in main]
    if rest and rest_share >= 15:
        # 종목이 수백 개인 포트폴리오는 "기타"가 절반을 넘기도 한다. 그럴 때는 기타를
        # 오른쪽 기둥 하나로 빼고, 이름 있는 종목들만 왼쪽에 배치한다.
        wm = W * (100 - rest_share) / 100
        placed = squarify(items, wm, H) + [(None, wm, 0.0, W - wm, H)]
    else:
        if rest:
            items.append((None, sum(r["value"] for r in rest)))
            items.sort(key=lambda it: -it[1])   # squarify는 면적 내림차순을 가정한다
        placed = squarify(items, W, H)
    return placed, rest, rest_share


def tile_class(r: dict) -> str:
    """칸의 색. 신규와 5% 이상 변화는 진하게, 그보다 작은 변화는 옅게."""
    if r.get("st") not in ("new", "add", "trim"):
        return "s-nt"
    soft = r["st"] != "new" and r["pct"] is not None and abs(r["pct"]) < 5
    return "s-" + tone(r) + ("2" if soft else "")


def treemap_html(q: dict) -> tuple[str, int]:
    W, H = 760.0, 520.0
    placed, rest, rest_share = treemap_layout(q["rows"], W, H)
    tiles = []
    for r, x, y, w, h in placed:
        a = w * h
        if a >= 55000 and w >= 180:
            tier = "xl"
        elif a >= 26000 and w >= 140:
            tier = "lg"
        elif a >= 11000 and w >= 90 and h >= 70:
            tier = "md"
        elif w >= 62 and h >= 50:
            tier = "sm"
        elif w >= 40 and h >= 22:
            tier = "xs"
        else:
            tier = "no"
        pos = f"left:{x / W * 100:.2f}%;top:{y / H * 100:.2f}%;width:{w / W * 100:.2f}%;height:{h / H * 100:.2f}%"
        if r is None:
            label = L["etc_n"].format(n=len(rest))
            inner = ""
            if tier in ("xl", "lg", "md"):
                inner = f'<span class="tk">{label}</span><span class="wt">{rest_share:.1f}%</span>'
            elif tier == "sm":
                inner = f'<span class="tk">{L["etc"]}</span><span class="wt">{rest_share:.1f}%</span>'
            elif tier == "xs":
                inner = f'<span class="tk">{L["etc"]}</span>'
            tiles.append(f'<div class="tile etc t-{tier}" style="{pos}" title="{label} · {L["sum"]} {rest_share:.1f}%">{inner}</div>')
            continue
        moved = r["st"] in ("new", "add", "trim")
        cls = tile_class(r)
        chg = f'<span class="ch">{pct_txt(r)}</span>' if moved else ""
        wt = f'<span class="wt">{r["w"]:.1f}%</span>'
        label = tk_txt(r) if r["mapped"] else (nice(r["name"]).split() or ["?"])[0][:12]
        tk = f'<span class="tk">{e(label)}</span>'
        nm = f'<span class="nm">{e(name_txt(r) if r["mapped"] else nice(r["name"]))}</span>'
        if tier in ("xl", "lg"):
            inner = f"<span>{tk}{nm}</span><span>{chg}{wt}</span>"
        elif tier == "md":
            inner = f"{tk}<span>{chg}{wt}</span>"
        elif tier == "sm":
            inner = f"{tk}{chg or wt}"
        elif tier == "xs":
            inner = tk
        else:
            inner = ""
        tip = f"{tk_txt(r)} {name_txt(r)} · {r['w']:.1f}% · {pct_txt(r)}"
        if r["mapped"] and r["ticker"] in STOCK_PAGES:
            tiles.append(f'<a class="tile {cls} t-{tier}" href="{stock_url(r["ticker"])}" style="{pos}" title="{e(tip)}">{inner}</a>')
        else:
            tiles.append(f'<div class="tile {cls} t-{tier}" style="{pos}" title="{e(tip)}">{inner}</div>')
    return "\n".join(tiles), len(rest)


def moves_html(title: str, cls: str, rows: list[dict], total: float, sign: str) -> str:
    if not rows:
        return (f'<div class="mv"><div class="mvh {cls}"><h2>{title} 0</h2></div>'
                f'<p class="note">{L["none"]}</p></div>')
    li = "\n".join(
        f'<li><span class="n tk">{tk_link(r)}</span>'
        f'<span class="n pc {cls}">{pct_txt(r)}</span>'
        f'<span class="n est">{usd_est(r["est"], sign)}</span></li>'
        for r in rows[:MAX_MOVES])
    more = f'<p class="note">{L["moves_more"].format(n=len(rows) - MAX_MOVES)}</p>' if len(rows) > MAX_MOVES else ""
    return (f'<div class="mv"><div class="mvh {cls}"><h2>{title} {len(rows)}</h2>'
            f'<span class="n">{L["est"]} {usd_est(total, sign)}</span></div>\n<ul>\n{li}\n</ul>{more}</div>')


def table_rows(rows: list[dict], wmax: float) -> str:
    out = []
    for r in rows:
        t = tone(r)
        out.append(
            f'<tr><th scope="row"><div class="tkc"><span class="n tk">{tk_link(r)}</span>'
            f'<span class="nm">{e(name_txt(r))}</span></div></th>'
            f'<td><div class="wcell"><span class="bar"><i style="width:{r["w"] / wmax * 100:.1f}%"></i></span>'
            f'<span class="n">{w_txt(r["w"])}</span></div></td>'
            f'<td class="n r">{usd_tbl(r["value"])}</td>'
            f'<td class="n r mt">{r["shares"]:,}</td>'
            f'<td class="n r {t}">{pct_txt(r)}</td></tr>')
    return "\n".join(out)


COLS = ('<colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"></colgroup>')


def holdings_html(q: dict) -> str:
    rows = q["rows"]
    wmax = (rows[0]["w"] if rows else 0) or 1
    h = L["th"]
    head = (f'<thead><tr><th scope="col">{h[0]}</th><th scope="col">{h[1]}</th><th scope="col" class="r">{h[2]}</th>'
            f'<th scope="col" class="r">{h[3]}</th><th scope="col" class="r">{h[4]}</th></tr></thead>')
    first, rest = rows[:10], rows[10:MAX_TABLE_ROWS]
    out = [f'<div class="scroll"><table>{COLS}{head}<tbody>\n{table_rows(first, wmax)}\n</tbody></table></div>']
    if rest:
        share = sum(r["w"] for r in rows[10:])
        out.append(
            f'<details><summary>{L["more_rows"].format(n=len(rows) - 10, p=f"{share:.1f}")}</summary>'
            f'<div class="scroll"><table>{COLS}<tbody>\n{table_rows(rest, wmax)}\n</tbody></table></div>')
        if len(rows) > MAX_TABLE_ROWS:
            out.append(f'<p class="note">{L["capped"].format(m=MAX_TABLE_ROWS, n=f"{len(rows):,}")}</p>')
        out.append("</details>")
    return "\n".join(out)


def history_html(m: dict, quarters: list[dict], idx: int, latest: str) -> str:
    by = {q["period"]: q for q in quarters}
    span, p = [], quarters[idx]["period"]
    for _ in range(8):
        span.append(p)
        p = prev_period(p)
    span.reverse()
    while span and span[0] not in by:
        span.pop(0)
    top = max(by[p]["total"] for p in span if p in by)
    cols = []
    for p in span:
        if p not in by:
            cols.append(f'<div class="col gap"><div class="plot"><span>{L["no_data"]}</span></div>'
                        f'<div class="ql n">{qshort(p)}</div><div class="qn">—</div></div>')
            continue
        q = by[p]
        cur = ' aria-current="true"' if p == quarters[idx]["period"] else ""
        count = L["count"].format(n=format(len(q["rows"]), ","))
        cols.append(
            f'<a class="col" href="{whale_url(m, p, latest)}"{cur}><div class="plot">'
            f'<span class="n">${q["total"] / 1e9:.0f}B</span>'
            f'<i style="height:{q["total"] / top * 160:.0f}px"></i></div>'
            f'<div class="ql n">{qshort(p)}</div><div class="qn">{count}</div></a>')
    return "\n".join(cols)


def switcher_html(m: dict, quarters: list[dict], idx: int, latest: str) -> str:
    def arrow(i, label, d):
        svg = f'<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="{d}"/></svg>'
        if 0 <= i < len(quarters):
            p = quarters[i]["period"]
            return f'<a class="sw" href="{whale_url(m, p, latest)}" aria-label="{label} {qlabel(p)}">{svg}</a>'
        return f'<span class="sw off" aria-hidden="true">{svg}</span>'
    return (arrow(idx - 1, L["prev_q"], "M10 3 5 8l5 5")
            + f'<span class="sw now n">{qlabel(quarters[idx]["period"])}</span>'
            + arrow(idx + 1, L["next_q"], "m6 3 5 5-5 5"))


# ------------------------------------------------------------------ 페이지

def render_whale(m: dict, quarters: list[dict], idx: int) -> str:
    q = quarters[idx]
    latest = quarters[-1]["period"]
    by = {x["period"]: x for x in quarters}
    prev = by.get(prev_period(q["period"]))
    mv = q["mv"] if "mv" in q else diff(q, prev, SPLITS)
    rows, meta = q["rows"], q["meta"]
    top10 = sum(r["w"] for r in rows[:10])
    tiles, n_rest = treemap_html(q)
    name = mfield(m, "name")
    home = PREFIX[LANG] + "/"

    place = f" · {e(mfield(m, 'place'))}" if mfield(m, "place") else ""
    filed = f" · {L['filed']} {dot(meta.get('filed', ''))}" if meta.get("filed") else ""
    src = "" if str(meta.get("source", "")).startswith("EDGAR") else f" · {L['temp_src']}"
    stats = [(L["stat_total"], usd_head(q["total"])), (L["stat_count"], f"{len(rows):,}"),
             (L["stat_top10"], f"{top10:.1f}%")]
    if mv:
        c = mv["total_chg"]
        stats.append((L["stat_qoq"], f"{'+' if c >= 0 else MINUS}{abs(c):.1f}%"))
    else:
        stats.append((L["stat_qoq"], "—"))
    stats_html = "\n".join(f'<div><span>{k}</span><b class="n">{v}</b></div>' for k, v in stats)

    if mv:
        rail = (moves_html(L["buys"], "up", mv["buys"], mv["buy_total"], "+")
                + moves_html(L["sells"], "dn", mv["sells"], mv["sell_total"], MINUS)
                + f'<p class="note">{L["est_note"]}</p>')
        if mv.get("splits"):
            done = ", ".join(f"{e(t)} {market.split_label(k)}" for t, k in sorted(mv["splits"].items()))
            rail += f'<p class="note">{L["split_note"].format(list=done)}</p>'
        cap = L["cap"]
    else:
        rail = f'<div class="mv"><p class="note">{L["noprev"].format(q=qlabel(prev_period(q["period"])))}</p></div>'
        cap = L["cap_noprev"]
    rest_note = f'<p class="note">{L["rest_note"].format(n=n_rest)}</p>' if n_rest else ""
    ended = (f'<p class="ended"><b>{L["ended"]}</b>{e(mfield(m, "ended_note"))}</p>'
             if m.get("status") == "ended" else "")
    if m.get("note"):
        ended += f'<p class="ended"><b>{L["note"]}</b>{e(mfield(m, "note"))}</p>'
    acc = f' · {L["accession"]} {e(meta["accession"])}' if meta.get("accession") else ""

    body = f"""
<div class="head">
<div>
<p class="crumb"><a href="{home}">{L['nav']}</a> / {e(name)}</p>
<h1>{e(name)}</h1>
<p class="meta">{e(m['en'])}{place} · {L['as_of']} {dot(q['period'])}{filed}{src}</p>
</div>
<div class="switch">{switcher_html(m, quarters, idx, latest)}</div>
</div>
{ended}
<div class="stats">
{stats_html}
</div>
<div class="hero">
<section class="map">
<div class="maph"><h2>{L['map']}</h2>
<div class="legend"><span><i class="up"></i>{L['lg_up']}</span><span><i class="dn"></i>{L['lg_dn']}</span><span><i class="nt"></i>{L['lg_nt']}</span></div></div>
<p class="cap">{cap}</p>
<div class="tm">
{tiles}
</div>
{rest_note}
</section>
<aside>
{rail}
</aside>
</div>

<section>
<h2>{L['hist']}</h2>
<p class="cap">{L['hist_cap']}</p>
<div class="hist">
{history_html(m, quarters, idx, latest)}
</div>
</section>

<section>
<h2>{L['holdings']}</h2>
{holdings_html(q)}
<p class="src"><a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK={int(m['cik']):010d}&amp;type=13F-HR">{L['sec']}</a>{acc}</p>
</section>
"""
    person = person_name(m)
    fmt = dict(name=name, person=person, q=qlabel(q["period"]), site=L["site"],
               total=usd_head(q["total"]), n=f"{len(rows):,}")
    title = L["page_title_p" if person else "page_title"].format(**fmt)
    desc = L["page_desc_p" if person else "page_desc"].format(**fmt)
    paths = {lg: whale_url(m, q["period"], latest, lg) for lg in LANGS}
    og = og_path(f"{m['slug']}-{qslug(latest)}") if q["period"] == latest else ""
    return page(title, desc, body, paths, section="whales", og=og)


def render_home(entries: list[dict]) -> str:
    """entries: {m, quarters} — quarters가 비면 아직 수집 전이다."""
    live = [x for x in entries if x["quarters"]]
    wait = [x for x in entries if not x["quarters"] and x["m"].get("status") != "ended"]
    ended_nodata = [x for x in entries if not x["quarters"] and x["m"].get("status") == "ended"]
    live.sort(key=lambda x: -x["quarters"][-1]["total"])
    newest = max((x["quarters"][-1]["period"] for x in live), default="")

    rows = []
    for x in live:
        m, qs = x["m"], x["quarters"]
        q = qs[-1]
        mv = q["mv"] if "mv" in q else diff(q, {y["period"]: y for y in qs}.get(prev_period(q["period"])), SPLITS)
        top = q["rows"][0]
        chips = ""
        if mv:
            picks = sorted(mv["buys"] + mv["sells"], key=lambda r: -r["est"])[:3]
            chips = "".join(
                f'<span class="chip"><b class="{tone(r)}">{L["kind"][r["st"]]}</b>'
                f'<span class="n">{e(tk_txt(r))}{"" if r["st"] in ("new", "exit") else " " + pct_txt(r)}</span></span>'
                for r in picks)
        tag = ""
        if m.get("status") == "ended":
            tag = f'<span class="tag">{L["ended"]} · {L["basis"].format(q=qlabel(q["period"]))}</span>'
        elif q["period"] != newest:
            tag = f'<span class="tag">{L["basis"].format(q=qlabel(q["period"]))}</span>'
        person = f" · {e(mfield(m, 'person'))}" if mfield(m, "person") else ""
        rows.append(
            f'<a class="row" href="{PREFIX[LANG]}/whales/{m["slug"]}/">'
            f'<span class="who"><b>{e(mfield(m, "name"))}</b>{tag}<small>{e(m["en"])}{person}</small></span>'
            f'<span class="n num">{usd_tbl(q["total"])}</span>'
            f'<span class="n num">{len(q["rows"]):,}</span>'
            f'<span class="topc"><span class="n"><b>{e(tk_txt(top))}</b>{top["w"]:.1f}%</span>'
            f'<span class="bar"><i style="width:{top["w"]:.1f}%"></i></span></span>'
            f'<span class="chips">{chips}</span></a>')
    for x in ended_nodata:
        m = x["m"]
        rows.append(f'<div class="row off"><span class="who"><b>{e(mfield(m, "name"))}</b><span class="tag">{L["ended"]}</span>'
                    f'<small>{e(m["en"])} · {e(mfield(m, "person"))}</small></span>'
                    f'<span class="endn">{e(mfield(m, "ended_note"))}</span></div>')
    waiting = ""
    if wait:
        names = ", ".join(e(mfield(x["m"], "name")) for x in wait)
        waiting = f'<p class="note wait">{L["waiting"].format(n=len(wait))}{names}</p>'
    sub = f"{qlabel(newest)} · {L['as_of']} {dot(newest)}" if newest else L["empty"]
    c = L["home_cols"]
    body = f"""
<div class="head home">
<div>
<p class="crumb n">{sub}</p>
<h1>{L['home_h1']}</h1>
<p class="meta">{L['home_meta']}</p>
</div>
</div>
{home_summary(SUMMARIES.get(NEWEST))}
<div class="scroll">
<div class="list">
<div class="row lh"><span>{c[0]}</span><span class="num">{c[1]}</span><span class="num">{c[2]}</span><span>{c[3]}</span><span>{c[4]}</span></div>
{chr(10).join(rows)}
</div>
</div>
{waiting}
"""
    return page(L["home_title"], L["home_desc"], body, {lg: PREFIX[lg] + "/" for lg in LANGS}, section="whales")


# ------------------------------------------------------------------ 종목 페이지

def hist_periods() -> list[str]:
    span, p = [], NEWEST
    for _ in range(HIST_QUARTERS):
        span.append(p)
        p = prev_period(p)
    return span[::-1]


def stock_name(s: dict) -> str:
    return NAMES[LANG].get(s["ticker"]) or nice(s["name"])


def whale_a(m: dict) -> str:
    return f'<a href="{PREFIX[LANG]}/whales/{m["slug"]}/">{e(mfield(m, "name"))}</a>'


def stock_moves(s: dict) -> tuple[list, list, list]:
    """최신 분기 기준으로 (늘린 곳, 줄인 곳, 전부 판 곳). 최신 분기 자료가 없는 큰손은 세지 않는다."""
    cur = [h for h in s["holders"] if h["q"]["period"] == NEWEST]
    ups = [h for h in cur if h["r"]["st"] in ("new", "add")]
    dns = [h for h in cur if h["r"]["st"] == "trim"]
    exits = [h for h in s["exits"] if h["q"]["period"] == NEWEST]
    return ups, dns, exits


def holder_rows(items: list[dict], wmax: float, show_rank: bool = True) -> str:
    out = []
    for h in items:
        m, q, r = h["m"], h["q"], h["r"]
        tag = "" if q["period"] == NEWEST else f'<span class="tag">{L["basis"].format(q=qlabel(q["period"]))}</span>'
        opt = f'<span class="tag">{L["opt"][r["opt"]].strip()}</span>' if r["opt"] else ""
        rank = f'<span class="rkx">{L["rank"].format(n=h["rank"])}</span>' if show_rank and h["rank"] else ""
        out.append(
            f'<tr><th scope="row"><div class="tkc"><span class="wn">{whale_a(m)}</span>{opt}{tag}</div></th>'
            f'<td><div class="wcell"><span class="bar"><i style="width:{r["w"] / wmax * 100:.1f}%"></i></span>'
            f'<span class="n">{w_txt(r["w"])}</span>{rank}</div></td>'
            f'<td class="n r">{usd_tbl(r["value"])}</td>'
            f'<td class="n r mt">{r["shares"]:,}</td>'
            f'<td class="n r {tone(r)}">{pct_txt(r)}</td></tr>')
    return "\n".join(out)


def cell_html(c: dict | None) -> str:
    """분기별 움직임 표의 한 칸."""
    if c is None:
        return '<td class="na">–</td>'
    st = c["st"]
    if st == "none":
        return "<td></td>"
    if st == "exit":
        return f'<td><span class="c-x">{L["cell"]["exit"]}</span></td>'
    label = L["cell"].get(st) or pct_txt(c)
    return f'<td><span class="c{tile_class(c)[1:]}">{label}</span></td>'


def render_stock(s: dict, entries: list[dict]) -> str:
    tk, name = s["ticker"], stock_name(s)
    tracked = sum(1 for x in entries if x["quarters"] and x["m"].get("status") != "ended")
    ups, dns, exits = stock_moves(s)
    n_new = sum(1 for h in ups if h["r"]["st"] == "new")
    stats = [
        (L["st_holders"], L["n_whales"].format(n=len(s["holders"])), L["st_of"].format(n=tracked)),
        (L["st_value"], usd_head(s["value"]) if s["holders"] else "—", ""),
        (L["st_up"], L["n_whales"].format(n=len(ups)), L["st_new"].format(n=n_new) if n_new else ""),
        (L["st_dn"], L["n_whales"].format(n=len(dns) + len(exits)), L["st_exit"].format(n=len(exits)) if exits else ""),
    ]
    stats_html = "\n".join(
        f'<div><span>{k}</span><b class="n">{v}</b>{f"<small>{sub}</small>" if sub else ""}</div>'
        for k, v, sub in stats)

    h = L["st_th"]
    head = (f'<thead><tr><th scope="col">{h[0]}</th><th scope="col">{h[1]}</th><th scope="col" class="r">{h[2]}</th>'
            f'<th scope="col" class="r">{h[3]}</th><th scope="col" class="r">{h[4]}</th></tr></thead>')
    if s["holders"]:
        wmax = max(x["r"]["w"] for x in s["holders"]) or 1
        table = (f'<div class="scroll"><table>{COLS}{head}<tbody>\n'
                 f'{holder_rows(s["holders"], wmax)}\n</tbody></table></div>')
    else:
        table = f'<p class="note">{L["st_none"]}</p>'
    ex_html = ""
    if s["exits"]:
        ex_html = (f'<p class="exits"><b class="dn">{L["st_exits"]}</b>'
                   + ", ".join(whale_a(x["m"]) for x in s["exits"]) + "</p>")
    opts_html = ""
    if s["opts"]:
        wmax_o = max(x["r"]["w"] for x in s["opts"]) or 1
        opts_html = (f'<section>\n<h2>{L["st_opts"]}</h2>\n<p class="cap">{L["st_opts_cap"]}</p>\n'
                     f'<div class="scroll"><table>{COLS}<tbody>\n{holder_rows(s["opts"], wmax_o, False)}\n'
                     f'</tbody></table></div>\n</section>')

    periods = hist_periods()
    hist = market.stock_history(entries, tk, periods)
    hist_html = ""
    if hist:
        cols = '<col class="m1">' + '<col class="m2">' * len(periods)
        th = "".join(f'<th scope="col" class="n">{qshort(p)}</th>' for p in periods)
        trs = "\n".join(
            f'<tr><th scope="row">{whale_a(row["m"])}</th>{"".join(cell_html(c) for c in row["cells"])}</tr>'
            for row in hist)
        counts = "".join(
            '<td class="n">{}</td>'.format(
                sum(1 for row in hist if row["cells"][i] and row["cells"][i]["st"] not in ("none", "exit")) or "")
            for i in range(len(periods)))
        hist_html = (f'<section>\n<h2>{L["st_hist"]}</h2>\n<p class="cap">{L["st_hist_cap"]}</p>\n'
                     f'<div class="scroll"><table class="mx"><colgroup>{cols}</colgroup>'
                     f'<thead><tr><th scope="col">{h[0]}</th>{th}</tr></thead><tbody>\n{trs}\n'
                     f'<tr class="sumr"><th scope="row">{L["st_count_row"]}</th>{counts}</tr>\n'
                     f'</tbody></table></div>\n</section>')

    body = f"""
<div class="head">
<div>
<p class="crumb"><a href="{PREFIX[LANG]}/stocks/">{L['stocks']}</a> / <span class="n">{e(tk)}</span></p>
<h1>{e(name)} <span class="n tkh">{e(tk)}</span></h1>
<p class="meta">{e(nice(s['name']))} · {L['basis'].format(q=qlabel(NEWEST))}</p>
</div>
</div>
<div class="stats">
{stats_html}
</div>

<section>
<h2>{L['st_who']}</h2>
<p class="cap">{L['st_who_cap'].format(q=qlabel(NEWEST))}</p>
{table}
{ex_html}
</section>
{hist_html}
{opts_html}
"""
    fmt = dict(name=name, tk=tk, q=qlabel(NEWEST), site=L["site"], n=len(s["holders"]),
               b=len(ups), s=len(dns) + len(exits))
    return page(L["stock_title"].format(**fmt), L["stock_desc"].format(**fmt), body,
                {lg: stock_url(tk, lg) for lg in LANGS}, section="stocks")


KCOLS = '<colgroup><col class="k1"><col class="k2"><col class="k3"><col class="k4"></colgroup>'


def render_stocks_index(stocks: dict[str, dict]) -> str:
    """전용 페이지가 있는 종목의 목록. 보유한 큰손이 많은 순서다."""
    items = sorted((stocks[t] for t in STOCK_PAGES), key=lambda s: (-len(s["holders"]), -s["value"], s["ticker"]))
    top, rest = items[:INDEX_ROWS], items[INDEX_ROWS:]
    nmax = max((len(s["holders"]) for s in items), default=1) or 1
    c = L["stocks_cols"]
    rows = []
    for s in top:
        ups, dns, exits = stock_moves(s)
        b, d = len(ups), len(dns) + len(exits)
        moved = L["moved"].format(b=b, s=d) if b or d else "—"
        rows.append(
            f'<tr><th scope="row"><div class="tkc"><span class="n tk"><a href="{stock_url(s["ticker"])}">{e(s["ticker"])}</a></span>'
            f'<span class="nm">{e(stock_name(s))}</span></div></th>'
            f'<td><div class="wcell"><span class="bar"><i style="width:{len(s["holders"]) / nmax * 100:.0f}%"></i></span>'
            f'<span class="n">{L["n_whales"].format(n=len(s["holders"]))}</span></div></td>'
            f'<td class="n r">{usd_tbl(s["value"])}</td>'
            f'<td class="r mt">{moved}</td></tr>')
    more = ""
    if rest:
        links = "".join(f'<a class="n" href="{stock_url(s["ticker"])}">{e(s["ticker"])}</a>'
                        for s in sorted(rest, key=lambda s: s["ticker"]))
        more = f'<section>\n<h2>{L["stocks_more"]}</h2>\n<div class="tklist">{links}</div>\n</section>'
    body = f"""
<div class="head home">
<div>
<p class="crumb n">{qlabel(NEWEST)} · {L['as_of']} {dot(NEWEST)}</p>
<h1>{L['stocks_h1']}</h1>
<p class="meta">{L['stocks_meta'].format(n=f"{len(items):,}", q=qlabel(NEWEST))}</p>
</div>
</div>
<div class="scroll idx"><table>{KCOLS}
<thead><tr><th scope="col">{c[0]}</th><th scope="col">{c[1]}</th><th scope="col" class="r">{c[2]}</th><th scope="col" class="r">{c[3]}</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></div>
{more}
"""
    fmt = dict(q=qlabel(NEWEST), site=L["site"], n=f"{len(items):,}")
    return page(L["stocks_title"].format(**fmt), L["stocks_desc"].format(**fmt), body,
                {lg: PREFIX[lg] + "/stocks/" for lg in LANGS}, section="stocks")


# ------------------------------------------------------------------ 분기 요약

def who_txt(pairs: list[tuple], limit: int = 4) -> str:
    """"버크셔 신규 · 타이거 +32.0%" 꼴로 누가 어떻게 했는지 적는다."""
    parts = [f'{e(mfield(m, "name"))} {L["kind"][r["st"]] if r["st"] in ("new", "exit") else pct_txt(r)}'
             for m, r in pairs[:limit]]
    if len(pairs) > limit:
        parts.append(L["q_more"].format(n=len(pairs) - limit))
    return " · ".join(parts)


def summary_lists(sm: dict) -> dict:
    """분기 요약에서 화면에 올릴 것만 고른다. 확인하지 못한 분할 의심 종목은 뺀다."""
    sus = {t for (t, p) in list(SUSPECTS) + list(RENAMES) if p == sm["period"]}
    out = {"dropped": set()}
    for key in ("bought", "sold"):
        keep = []
        for s in sm[key]:
            if s["ticker"] in sus:
                out["dropped"].add(s["ticker"])
            elif len(keep) < MAX_RANK:
                keep.append(s)
        out[key] = keep
    for key in ("big_buys", "big_sells"):
        keep = []
        for mv in sm[key]:
            if mv[2]["ticker"] in sus:
                if len(keep) < MAX_RANK:
                    out["dropped"].add(mv[2]["ticker"])
            elif len(keep) < MAX_RANK:
                keep.append(mv)
        out[key] = keep
    out["held"] = sm["held"][:MAX_RANK]
    return out


def rank_block(title: str, cls: str, lis: list[str]) -> str:
    inner = "\n".join(lis) if lis else ""
    body = f"<ul>\n{inner}\n</ul>" if lis else f'<p class="note">{L["q_none"]}</p>'
    return f'<div class="mv rk"><div class="mvh {cls}"><h2>{title}</h2></div>\n{body}</div>'


def multi_li(s: dict, side: str, with_who: bool) -> str:
    pairs = s[side]
    who = f'<span class="who">{who_txt(pairs)}</span>' if with_who else ""
    return (f'<li><span class="n tk">{tk_link(s["r"])}</span><span class="nm">{e(name_txt(s["r"]))}</span>'
            f'<span class="n ct">{L["n_whales"].format(n=len(pairs))}</span>{who}</li>')


def move_li(mv: tuple) -> str:
    side, m, r = mv
    cls, sign = ("up", "+") if side == "buy" else ("dn", MINUS)
    return (f'<li><span class="n tk">{tk_link(r)}</span><span class="nm">{e(mfield(m, "name"))} · {pct_txt(r)}</span>'
            f'<span class="n ct {cls}">{usd_est(r["est"], sign)}</span></li>')


def render_quarter(sm: dict) -> str:
    period, ls = sm["period"], summary_lists(sm)
    q = qlabel(period)
    held = [f'<li><span class="n tk">{tk_link(s["r"])}</span><span class="nm">{e(name_txt(s["r"]))}</span>'
            f'<span class="n ct">{L["n_whales"].format(n=len(s["hold"]))} · {usd_tbl(sum(r["value"] for _, r in s["hold"]))}</span></li>'
            for s in ls["held"]]
    dropped = ""
    if ls["dropped"]:
        dropped = f'<p class="note">{L["q_suspect"].format(list=", ".join(sorted(ls["dropped"])))}</p>'
    cur = ' aria-current="true"'
    others = "".join(
        f'<a class="chip n" href="{quarter_url(p)}"{cur if p == period else ""}>{qlabel(p)}</a>'
        for p in reversed(QUARTER_PAGES))
    body = f"""
<div class="head home">
<div>
<p class="crumb n">{q} · {L['as_of']} {dot(period)}</p>
<h1>{L['q_h1'].format(q=q)}</h1>
<p class="meta">{L['q_meta'].format(n=len(sm['whales']))}</p>
</div>
</div>
<div class="grid2">
{rank_block(L['q_bought'], 'up', [multi_li(s, 'buy', True) for s in ls['bought']])}
{rank_block(L['q_sold'], 'dn', [multi_li(s, 'sell', True) for s in ls['sold']])}
{rank_block(L['q_bigbuy'], 'up', [move_li(mv) for mv in ls['big_buys']])}
{rank_block(L['q_bigsell'], 'dn', [move_li(mv) for mv in ls['big_sells']])}
</div>
<p class="note">{L['est_note']}</p>
{dropped}

<section>
<h2>{L['q_held']}</h2>
<p class="cap">{L['q_held_cap']}</p>
<div class="mv rk one"><ul>
{chr(10).join(held)}
</ul></div>
</section>

<section>
<h2>{L['q_other']}</h2>
<div class="chips qs">{others}</div>
</section>
"""
    a = ls["bought"][0]["ticker"] if ls["bought"] else "—"
    b = ls["sold"][0]["ticker"] if ls["sold"] else "—"
    fmt = dict(q=q, site=L["site"], n=len(sm["whales"]), a=a, b=b)
    return page(L["q_title"].format(**fmt), L["q_desc"].format(**fmt), body,
                {lg: quarter_url(period, lg) for lg in LANGS}, section="quarters")


def home_summary(sm: dict | None) -> str:
    """홈 맨 위에 올리는 이번 분기 요약. 자세한 것은 분기 요약 페이지에 있다."""
    if not sm:
        return ""
    ls = summary_lists(sm)
    big = sorted(ls["big_buys"] + ls["big_sells"], key=lambda mv: -mv[2]["est"])[:5]
    return f"""
<section class="qsum">
<div class="maph"><h2>{L['home_q'].format(q=qlabel(sm['period']))}</h2>
<a class="more" href="{quarter_url(sm['period'])}">{L['home_q_more']}</a></div>
<div class="grid3">
{rank_block(L['q_bought'], 'up', [multi_li(s, 'buy', False) for s in ls['bought'][:5]])}
{rank_block(L['q_sold'], 'dn', [multi_li(s, 'sell', False) for s in ls['sold'][:5]])}
{rank_block(L['q_big'], 'nt', [move_li(mv) for mv in big])}
</div>
</section>
"""


# ------------------------------------------------------------------ 안내 페이지

GUIDE = {
    "ko": """
<div class="head home">
<div>
<p class="crumb">13F 안내</p>
<h1>13F 읽는 법</h1>
<p class="meta">이 사이트의 숫자가 어디서 왔고, 어디까지 믿을 수 있는지 정리했습니다.</p>
</div>
</div>
<div class="prose">
<section>
<h2>13F란</h2>
<p>미국 상장 주식 같은 대상 증권을 1억 달러 이상 운용하는 기관 투자자는 분기마다 보유 내역을 미국 증권거래위원회(SEC)에 내야 합니다. 이 보고서가 Form 13F입니다. 분기가 끝나고 45일 안에 내며, 누구나 SEC 사이트에서 볼 수 있습니다.</p>
</section>
<section>
<h2>들어가는 것과 빠지는 것</h2>
<ul>
<li><b>들어가는 것</b> 미국 거래소에 상장된 주식과 ETF, 미국에 상장된 해외 기업 주식(ADR), 일부 옵션(풋·콜)과 전환사채.</li>
<li><b>빠지는 것</b> 공매도, 현금, 대부분의 채권, 미국 밖 거래소의 주식, 비상장 지분. 예를 들어 버크셔 해서웨이의 일본 종합상사 지분은 13F에 나오지 않습니다.</li>
<li><b>늦게 나오는 것</b> 기관이 SEC에 비공개를 요청하면 일부 종목은 몇 분기 뒤에야 공개됩니다.</li>
</ul>
</section>
<section>
<h2>읽을 때 알아둘 점</h2>
<ul>
<li><b>최대 45일 전의 모습입니다.</b> 13F는 분기 말 하루의 사진입니다. 그 뒤에 사고판 것은 다음 공시가 나올 때까지 알 수 없습니다.</li>
<li><b>분기 중에 사고판 것은 보이지 않습니다.</b> 분기 초에 샀다가 분기 말 전에 팔았다면 흔적이 남지 않습니다.</li>
<li><b>평가액은 분기 말 가격입니다.</b> 실제로 얼마에 샀는지는 13F에 없습니다.</li>
<li><b>옵션은 크게 잡힙니다.</b> 풋·콜은 옵션 가격이 아니라 기초자산의 명목 금액으로 적습니다. 그래서 옵션이 많은 곳은 공시 총액이 실제 투자금보다 커 보입니다.</li>
<li><b>전체 자산이 아닙니다.</b> 연금이나 재단은 13F에 나오는 미국 주식이 전체 자산의 일부일 뿐입니다.</li>
</ul>
</section>
<section>
<h2>이 사이트의 계산 방식</h2>
<ul>
<li><b>늘림·줄임</b> 직전 분기와 주식 수를 비교합니다. 가격이 올라 평가액이 커진 것은 늘림이 아닙니다.</li>
<li><b>추정 금액</b> 주식 수 변화에 분기 말 가격을 곱했습니다. 전부 판 종목은 직전 분기 말 평가액을 씁니다. 실제 거래 금액과는 다릅니다.</li>
<li><b>주식 분할</b> 공시로 확인한 분할은 분할 전 주식 수에 비율을 곱해 비교합니다. 아직 확인하지 못한 분할은 매수처럼 보일 수 있어, 분기 요약의 순위에서는 뺍니다.</li>
<li><b>분사와 종목 코드 변경</b> 회사가 사업부를 떼어 내 주주에게 새 주식을 나눠 주면 그 주식은 신규 매수처럼 보입니다. 회사 재편으로 종목 코드가 바뀌면 확인된 것만 같은 종목으로 잇습니다.</li>
<li><b>정정 공시</b> 기관이 공시를 고쳐 내면 고친 내용을 반영합니다.</li>
<li><b>종목 이름과 티커</b> 13F에는 티커가 없어 증권 식별 번호(CUSIP)로 찾습니다. 찾지 못한 종목은 CUSIP 번호로 표시합니다.</li>
<li><b>분기 요약</b> 직전 분기 자료가 있는 큰손만 셉니다. 종목이 수백 개인 곳은 거의 모든 종목을 조금씩 조정하므로, 주식 수를 5% 이상 바꾼 경우만 샀다·팔았다로 셉니다.</li>
<li><b>종목 페이지</b> 세 곳 이상이 들고 있거나 어느 한 곳의 상위 25위 안에 드는 종목에 만듭니다.</li>
<li><b>갱신</b> 평일마다 SEC에 새 공시가 있는지 확인합니다.</li>
</ul>
</section>
<section>
<h2>추적 대상</h2>
<p class="wl">{whales}</p>
</section>
<section>
<h2>투자 권유가 아닙니다</h2>
<p>이 사이트는 공개된 공시를 보기 쉽게 옮긴 것입니다. 큰손이 샀다는 사실이 지금 사도 된다는 뜻은 아닙니다. 공시가 나왔을 때는 이미 팔았을 수도 있습니다.</p>
</section>
</div>
""",
    "ja": """
<div class="head home">
<div>
<p class="crumb">13Fの読み方</p>
<h1>13Fの読み方</h1>
<p class="meta">このサイトの数字がどこから来て、どこまで信頼できるのかをまとめました。</p>
</div>
</div>
<div class="prose">
<section>
<h2>13Fとは</h2>
<p>米国上場株式などの対象証券を1億ドル以上運用する機関投資家は、四半期ごとに保有状況を米国証券取引委員会(SEC)に提出します。この報告書がForm 13Fです。四半期末から45日以内に提出され、誰でもSECのサイトで読めます。</p>
</section>
<section>
<h2>含まれるもの、含まれないもの</h2>
<ul>
<li><b>含まれるもの</b> 米国の取引所に上場する株式とETF、米国に上場する海外企業の株式(ADR)、一部のオプション(プット・コール)と転換社債。</li>
<li><b>含まれないもの</b> 空売り、現金、大半の債券、米国外の取引所の株式、非上場株。たとえばバークシャー・ハサウェイが保有する日本の総合商社株は13Fに出てきません。</li>
<li><b>遅れて出るもの</b> 機関投資家がSECに非開示を申請すると、一部の銘柄は数四半期後に公開されます。</li>
</ul>
</section>
<section>
<h2>読むときの注意点</h2>
<ul>
<li><b>最大45日前の姿です。</b> 13Fは四半期末の一日を写したものです。その後の売買は次の開示まで分かりません。</li>
<li><b>四半期の途中の売買は見えません。</b> 期初に買って期末までに売っていれば、跡は残りません。</li>
<li><b>評価額は四半期末の株価です。</b> 実際にいくらで買ったかは13Fに載っていません。</li>
<li><b>オプションは大きく見えます。</b> プット・コールはオプション価格ではなく原資産の想定元本で記載されます。オプションの多い投資家は、開示総額が実際の投資額より大きく見えます。</li>
<li><b>資産の全体ではありません。</b> 年金基金や財団の場合、13Fに載る米国株は資産全体の一部です。</li>
</ul>
</section>
<section>
<h2>このサイトの計算方法</h2>
<ul>
<li><b>買い増し・売り</b> 前四半期と株数を比べます。株価が上がって評価額が増えただけでは買い増しになりません。</li>
<li><b>推定金額</b> 株数の変化に四半期末の株価を掛けています。全売却は前四半期末の評価額です。実際の売買金額とは異なります。</li>
<li><b>株式分割</b> 開示で確認できた分割は、分割前の株数に比率を掛けて比べます。未確認の分割は買いに見えることがあるため、四半期まとめの順位からは除きます。</li>
<li><b>スピンオフと銘柄コードの変更</b> 企業が事業を切り離して株主に新しい株式を配ると、その株式は新規の買いに見えます。再編で銘柄コードが変わった場合は、確認できたものだけを同じ銘柄としてつなぎます。</li>
<li><b>訂正報告</b> 機関投資家が報告を訂正した場合は、訂正後の内容を反映します。</li>
<li><b>銘柄名とティッカー</b> 13Fにはティッカーがないため、証券識別番号(CUSIP)から調べます。見つからない銘柄はCUSIP番号で表示します。</li>
<li><b>四半期まとめ</b> 前四半期のデータがある投資家だけを数えます。数百銘柄を持つ投資家はほぼ全銘柄を少しずつ調整するため、株数を5%以上変えた場合だけを買い・売りとして数えます。</li>
<li><b>銘柄ページ</b> 3社以上が保有しているか、いずれかの投資家の上位25位に入る銘柄に作成します。</li>
<li><b>更新</b> 平日は毎日、SECに新しい開示があるかを確認します。</li>
</ul>
</section>
<section>
<h2>追跡対象</h2>
<p class="wl">{whales}</p>
</section>
<section>
<h2>投資勧誘ではありません</h2>
<p>このサイトは公開された開示情報を見やすく整理したものです。大口投資家が買ったという事実は、いま買ってよいという意味ではありません。開示が出た時点で、すでに売却している可能性もあります。</p>
</section>
</div>
""",
}


def render_guide(entries: list[dict]) -> str:
    whales = ", ".join(whale_a(x["m"]) if x["quarters"] else e(mfield(x["m"], "name")) for x in entries)
    body = GUIDE[LANG].replace("{whales}", whales)
    return page(L["guide_title"].format(site=L["site"]), L["guide_desc"], body,
                {lg: PREFIX[lg] + "/guide/" for lg in LANGS}, section="guide")



CSS = """
:root{--bg:#0D1117;--sf:#161C25;--ln:#2A323E;--tx:#E8ECF2;--mt:#9BA6B5;--ft:#8793A3;--up:#FF8A4C;--dn:#7AA7FF;--tile:#232B37;--txt:"Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif}
:root:lang(ja){--txt:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic UI","Yu Gothic","Meiryo","Noto Sans JP",system-ui,sans-serif}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 var(--txt)}
.n{font-family:"Space Grotesk",var(--txt);font-variant-numeric:tabular-nums}
a{color:inherit}a:hover{color:var(--up)}
h1,h2,p,ul{margin:0}ul{padding:0;list-style:none}
.wrap{max-width:1200px;margin:0 auto;padding:0 32px}
.top{border-bottom:1px solid var(--ln)}
.top .wrap{min-height:64px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:4px 24px}
.brand{font-size:17px;font-weight:700;letter-spacing:-.01em;text-decoration:none;padding:10px 0}
.langs{display:flex;gap:2px;font-size:13px}
.langs a{padding:12px 8px;color:var(--mt);text-decoration:none}
.langs a[aria-current]{color:var(--tx);font-weight:700}
main.wrap{padding-top:40px;padding-bottom:48px}
.head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:24px 32px}
.crumb{font-size:13px;color:var(--mt)}.crumb a{text-underline-offset:4px}
h1{margin-top:10px;font-size:40px;line-height:1.2;font-weight:700;letter-spacing:-.02em}
.meta{margin-top:8px;color:var(--mt)}
.switch{display:flex;align-items:center;gap:8px}
.sw{min-width:44px;height:44px;display:flex;align-items:center;justify-content:center;border:1px solid var(--ln);border-radius:6px;background:var(--sf);text-decoration:none}
.sw.now{padding:0 18px;border-color:var(--tx);background:var(--tx);color:var(--bg);font-size:16px;font-weight:700}
.sw.off{background:var(--bg);color:var(--ft)}
.ended{margin-top:20px;padding:12px 16px;border:1px solid var(--ft);border-radius:6px;color:var(--mt)}
.ended b{margin-right:10px;color:var(--tx)}
.hero{margin-top:32px;display:flex;flex-wrap:wrap;gap:32px}
.map{flex:2 1 520px;min-width:0}
aside{flex:1 1 300px;min-width:0;display:flex;flex-direction:column;gap:28px}
h2{font-size:20px;font-weight:700;letter-spacing:-.01em}
.maph{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px 24px}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;color:var(--mt)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:12px;height:12px}
.legend .up{background:var(--up)}.legend .dn{background:#2A55BD}.legend .nt{background:var(--tile);border:1px solid var(--ft)}
.cap{margin-top:4px;font-size:14px;color:var(--mt)}
.note{margin-top:12px;font-size:13px;color:var(--mt);text-wrap:pretty}
.tm{margin-top:16px;position:relative;width:100%;aspect-ratio:760/520;container-type:inline-size;font-family:"Space Grotesk",var(--txt)}
.tile{position:absolute;border:2px solid var(--bg);overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;line-height:1.15;background:var(--tile);color:var(--tx)}
.tile span{display:block}.tile .tk{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tile .nm{margin-top:.5cqw;color:#AEB8C6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile .ch{font-weight:700}.tile .wt{font-weight:500}
.tile.s-up{background:#FF8A4C;color:#1A0E06}.tile.s-up2{background:#6B3A1E;color:#FFD8C2}
.tile.s-dn{background:#2A55BD;color:#fff}.tile.s-dn2{background:#1F3A7A;color:#DCE6FF}
.tile.s-up .nm,.tile.s-up2 .nm,.tile.s-dn .nm,.tile.s-dn2 .nm{color:inherit}
.tile.etc{background:#1A212B;color:#AEB8C6}
.t-xl{padding:1.8cqw}.t-xl .tk{font-size:clamp(15px,4.4cqw,36px)}.t-xl .nm{font-size:clamp(10px,1.7cqw,14px)}.t-xl .wt,.t-xl .ch{font-size:clamp(12px,2.8cqw,22px)}
.t-lg{padding:1.5cqw}.t-lg .tk{font-size:clamp(13px,3cqw,24px)}.t-lg .nm{font-size:clamp(9px,1.6cqw,13px)}.t-lg .wt,.t-lg .ch{font-size:clamp(11px,2.2cqw,18px)}
.t-md{padding:1.3cqw}.t-md .tk{font-size:clamp(11px,2.3cqw,18px)}.t-md .wt,.t-md .ch{font-size:clamp(10px,1.9cqw,15px)}
.t-sm{padding:1cqw}.t-sm .tk{font-size:clamp(9px,1.7cqw,13px)}.t-sm .wt,.t-sm .ch{font-size:clamp(9px,1.6cqw,12px)}
.t-xs{padding:.6cqw;justify-content:center}.t-xs .tk{font-size:clamp(8px,1.45cqw,11px)}
.stats{margin-top:28px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));gap:12px}
.stats div{padding:14px 16px;border-radius:6px;background:var(--sf)}
.stats span{display:block;font-size:13px;color:var(--mt)}.stats b{font-size:24px}
.mvh{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding-bottom:8px;border-bottom:2px solid}
.mvh h2{font-size:16px}.mvh span{font-size:14px;color:var(--tx)}
.mvh.up{color:var(--up);border-color:var(--up)}.mvh.dn{color:var(--dn);border-color:var(--dn)}
.mv li{display:grid;grid-template-columns:minmax(64px,auto) minmax(0,1fr) auto;column-gap:12px;align-items:baseline;padding:9px 0;border-bottom:1px solid var(--ln)}
.mv .tk{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mv .pc{font-weight:700}.mv .est{font-size:14px;color:var(--mt)}
.up{color:var(--up)}.dn{color:var(--dn)}.nt,.mt{color:var(--mt)}
section{margin-top:64px}.hero section{margin-top:0}
.hist{margin-top:20px;padding:20px 20px 16px;border-radius:6px;background:var(--sf);display:flex;gap:14px}
.col{flex:1 1 0;min-width:0;display:flex;flex-direction:column;gap:6px;text-align:center;font-size:13px;text-decoration:none}
.plot{height:190px;display:flex;flex-direction:column;justify-content:flex-end;gap:6px}
.plot span{font-weight:500}.plot i{display:block;border-radius:3px 3px 0 0;background:#5B6676}
.col[aria-current] .plot i{background:var(--tx)}a.col:hover .plot i{background:var(--up)}
.gap .plot{justify-content:center;border:1px dashed var(--ln);border-radius:3px;color:var(--ft);font-size:12px}
.ql{padding-top:6px;border-top:1px solid var(--ft)}.qn{color:var(--mt)}
.scroll{overflow-x:auto}
table{width:100%;min-width:760px;border-collapse:collapse;table-layout:fixed;font-variant-numeric:tabular-nums}
.c1{width:30%}.c2{width:32%}.c3{width:11%}.c4{width:16%}.c5{width:11%}
section>.scroll{margin-top:16px}
th,td{padding:11px 0;border-bottom:1px solid var(--ln);text-align:left;font-weight:400;vertical-align:middle}
thead th{padding:8px 0;border-color:var(--ft);font-size:13px;color:var(--mt)}
.r{text-align:right}td.r,th.r{padding-left:12px}
.tkc{display:flex;align-items:baseline;gap:10px;min-width:0;padding-right:16px}
.tkc .tk{font-weight:700;white-space:nowrap}.tkc .nm{font-size:14px;color:var(--mt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wcell{display:flex;align-items:center;gap:12px;padding-right:8px}
.wcell .n{width:74px;text-align:right;font-weight:500}
.bar{flex:1 1 0;display:block;height:8px;border-radius:4px;background:var(--tile)}.bar i{display:block;height:8px;border-radius:4px;background:var(--tx)}
td.up,td.dn{font-weight:700}
details{margin-top:16px}
summary{min-height:48px;display:flex;align-items:center;justify-content:center;border:1px solid var(--ft);border-radius:6px;background:var(--sf);font-weight:700;cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}
details[open] summary{margin-bottom:8px}
.src{margin-top:16px;font-size:13px;color:var(--mt)}.src a{font-weight:700;color:var(--tx);text-underline-offset:4px}
footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--ln);display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px 32px;font-size:13px;color:var(--mt)}
footer p{max-width:720px;text-wrap:pretty}
.home h1{font-size:44px}
.list{margin-top:36px;min-width:980px}
.row{display:grid;grid-template-columns:minmax(220px,2fr) 100px 70px minmax(160px,1.3fr) minmax(320px,3fr);column-gap:20px;align-items:center;padding:18px 0;border-bottom:1px solid var(--ln);text-decoration:none}
.row.lh{padding:8px 0;border-color:var(--ft);font-size:13px;color:var(--mt)}
a.row:hover{color:inherit;background:var(--sf)}
.who b{font-size:17px;letter-spacing:-.01em}.who small{display:block;font-size:13px;color:var(--mt)}
.tag{margin-left:8px;padding:2px 7px;border:1px solid var(--ft);border-radius:4px;font-size:12px;color:var(--mt);white-space:nowrap}
.num{text-align:right}.row .num{font-size:16px;font-weight:700}.row.lh .num{font-size:13px;font-weight:400}
.topc{display:flex;flex-direction:column;gap:6px}.topc .n{display:flex;justify-content:space-between;font-size:14px}
.topc .bar,.topc .bar i{height:4px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:baseline;gap:6px;padding:4px 8px;border-radius:4px;background:var(--sf);font-size:13px;white-space:nowrap}
.row.off{grid-template-columns:minmax(220px,2fr) minmax(0,6fr);color:var(--mt)}.endn{font-size:14px}
.wait{margin-top:20px}
.top nav{display:flex;flex-wrap:wrap;gap:2px;margin:0 auto 0 12px;font-size:14px}
.top nav a{padding:12px 10px;color:var(--mt);text-decoration:none}
.top nav a[aria-current]{color:var(--tx);font-weight:700}
a.tile{text-decoration:none}a.tile:hover{filter:brightness(1.15)}a.tile.s-nt:hover,a.tile.etc:hover{color:var(--tx)}
.tk a,.wn a,.mx a{text-decoration:none}.tk a:hover,.wn a:hover,.mx a:hover{text-decoration:underline}
.stats small{display:block;margin-top:2px;font-size:12px;color:var(--mt)}
.tkh{margin-left:8px;font-size:.5em;font-weight:500;color:var(--mt)}
.wn{font-weight:700;white-space:nowrap}.tkc .tag{margin-left:0}
.rkx{width:40px;font-size:12px;color:var(--mt);text-align:right;white-space:nowrap}
.exits{margin-top:16px;font-size:14px;color:var(--mt)}.exits b{margin-right:10px}.exits a{color:var(--tx);text-underline-offset:4px}
.mx{min-width:720px}.m1{width:24%}
.mx th,.mx td{padding:5px 3px}.mx thead th{padding:8px 3px;text-align:center}.mx thead th:first-child,.mx tbody th{text-align:left}
.mx td{text-align:center;font-size:13px}
.mx td span{display:block;padding:6px 2px;border-radius:4px;font-weight:700;white-space:nowrap}
.c-up{background:#FF8A4C;color:#1A0E06}.c-up2{background:#6B3A1E;color:#FFD8C2}.c-dn{background:#2A55BD;color:#fff}.c-dn2{background:#1F3A7A;color:#DCE6FF}
.mx td .c-nt{background:var(--tile);color:var(--mt);font-weight:400}
.c-x{border:1px dashed var(--dn);color:var(--dn)}
.mx .na{color:var(--ft)}
.sumr th,.sumr td{border-bottom:0;font-size:13px;color:var(--mt)}
.k1{width:42%}.k2{width:26%}.k3{width:14%}.k4{width:18%}
.idx{margin-top:36px}
.tklist{margin-top:16px;display:flex;flex-wrap:wrap;gap:6px}
.tklist a{padding:9px 10px;border-radius:4px;background:var(--sf);font-size:13px;text-decoration:none}
.grid2{margin-top:36px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:36px 48px}
.grid3{margin-top:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr));gap:28px 36px}
.rk li{grid-template-columns:minmax(56px,auto) minmax(0,1fr) auto;row-gap:2px}
.rk .nm{font-size:14px;color:var(--mt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rk .ct{font-weight:700;white-space:nowrap}
.rk .who{grid-column:1/-1;font-size:13px;color:var(--mt)}
.rk.one{margin-top:16px;max-width:720px}
.mvh.nt{color:var(--tx);border-color:var(--ft)}
.qsum{margin-top:36px}.qsum .more{font-size:14px;color:var(--mt);text-underline-offset:4px}
.chips.qs{margin-top:16px}.chips.qs a{padding:10px 14px;text-decoration:none}.chips.qs a[aria-current]{background:var(--tx);color:var(--bg);font-weight:700}
.prose{max-width:760px}.prose section{margin-top:44px}.prose p,.prose ul{margin-top:12px;line-height:1.7;color:#C9D1DC}
.prose li{margin-top:10px;padding-left:14px;border-left:2px solid var(--ln)}.prose li b{margin-right:8px;color:var(--tx)}
.prose .wl a{text-underline-offset:4px}
@media (max-width:640px){.wrap{padding:0 16px}h1{font-size:30px}.home h1{font-size:32px}.hist{gap:6px;padding:14px 10px}.col{font-size:11px}.stats b{font-size:20px}.top nav{margin-left:0;order:3;width:100%}}
"""


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def inputs_digest() -> str:
    """사이트를 만드는 데 들어가는 모든 파일의 지문. site/build.txt에 적어 둔다.

    소스나 데이터를 고치고 사이트를 다시 만들지 않으면 scripts/check_site.py가 이 값으로 알아챈다.
    """
    paths = [os.path.join(ROOT, "managers.json")]
    for d, pat in ((HERE, r".*\.(py|json)$"), (os.path.join(ROOT, "pipeline"), r".*\.json$")):
        paths += [os.path.join(d, f) for f in os.listdir(d) if re.fullmatch(pat, f)]
    for d, _, files in os.walk(RAW):
        paths += [os.path.join(d, f) for f in files if f.endswith(".json")]
    h = hashlib.sha256()
    for path in sorted(paths, key=lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")):
        h.update(os.path.relpath(path, ROOT).replace(os.sep, "/").encode())
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def write_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# ------------------------------------------------------------------ 미리보기 그림

def og_tiles(rows: list[dict]) -> list[tuple]:
    """트리맵을 미리보기 그림의 칸으로 옮긴다. 글자는 영문·숫자만 쓸 수 있다."""
    placed, rest, rest_share = treemap_layout(rows, ogimage.MAP_W, ogimage.MAP_H)
    tiles = []
    for r, x, y, w, h in placed:
        if r is None:
            tiles.append(("OTHER", f"{rest_share:.1f}%", "etc", x, y, w, h))
            continue
        label = r["ticker"] if r["mapped"] else (r["name"].split() or [""])[0]
        if r["opt"]:
            label += " " + r["opt"]
        tiles.append((label, f"{r['w']:.1f}%", tile_class(r), x, y, w, h))
    return tiles


def og_whale(m: dict, q: dict) -> bytes:
    sub = f"13F PORTFOLIO   {qlabel(q['period'])}   {usd_head(q['total'])}   {len(q['rows']):,} HOLDINGS"
    return ogimage.card(m["en"], sub, og_tiles(q["rows"]))


def og_site(stocks: dict[str, dict], n_whales: int) -> bytes:
    """사이트 대표 그림. 큰손들이 합쳐서 가장 많이 들고 있는 종목을 면적으로 보여 준다."""
    top = sorted((s for s in stocks.values() if s["holders"]), key=lambda s: -s["value"])[:60]
    total = sum(s["value"] for s in top) or 1
    rows = []
    for s in top:
        ups, dns, exits = stock_moves(s)
        st = "add" if len(ups) > len(dns) + len(exits) else "trim" if len(dns) + len(exits) > len(ups) else "keep"
        rows.append({"ticker": s["ticker"], "name": s["name"], "mapped": True, "opt": "", "value": s["value"],
                     "w": s["value"] / total * 100, "st": st, "pct": 100.0, "n": len(s["holders"])})
    placed, rest, rest_share = treemap_layout(rows, ogimage.MAP_W, ogimage.MAP_H)
    tiles = [("OTHER", "", "etc", x, y, w, h) if r is None
             else (r["ticker"], f"{r['n']} FUNDS", tile_class(r), x, y, w, h)
             for r, x, y, w, h in placed]
    sub = f"13F FILINGS   {qlabel(NEWEST)}   {n_whales} INVESTORS TRACKED"
    return ogimage.card("WHAT THE WHALES HOLD", sub, tiles)


def main() -> None:
    global NEWEST
    managers = _json(os.path.join(ROOT, "managers.json"), [])
    tmap = load_tmap()
    for lang in LANGS:
        NAMES[lang] = _json(os.path.join(HERE, f"names_{lang}.json"), {})

    # 생성물만 지운다. site/privacy.html 같은 손으로 쓴 파일은 그대로 둔다.
    for stale in ("whales", "stocks", "quarters", "guide", "assets", "data", "ja"):
        shutil.rmtree(os.path.join(SITE, stale), ignore_errors=True)
    write(os.path.join(SITE, "assets", "style.css"), CSS.strip() + "\n")
    # Cloudflare Pages는 site/_redirects를 읽는다. 쿼리스트링(?manager=...)은 구분하지 못한다.
    write(os.path.join(SITE, "_redirects"),
          "".join(f"{p} / 301\n{p}/* / 301\n" for p in OLD_PATHS))
    write(os.path.join(SITE, "robots.txt"), f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")

    entries = [{"m": m, "quarters": load_manager(m, tmap)} for m in managers]
    live = [x for x in entries if x["quarters"] and x["m"].get("status") != "ended"]

    # 주식 분할. 손으로 확인한 것만 계산에 반영하고, 추정뿐인 것은 순위에서 빼기만 한다.
    pinned, vetoed = market.pinned_splits(_json(os.path.join(ROOT, "pipeline", "splits.json"), {}))
    SPLITS.clear()
    SPLITS.update(pinned)
    SUSPECTS.clear()
    SUSPECTS.update({k: v for k, v in market.find_splits(entries).items() if k not in pinned and k not in vetoed})
    for x in entries:
        by = {q["period"]: q for q in x["quarters"]}
        for q in x["quarters"]:
            q["mv"] = diff(q, by.get(prev_period(q["period"])), SPLITS)

    RENAMES.clear()
    RENAMES.update(market.find_renames(entries))

    latest = [x["quarters"][-1]["period"] for x in live]
    NEWEST = max(set(latest), key=lambda p: (latest.count(p), p)) if latest else ""
    stocks = market.collect_stocks(entries)
    SUMMARIES.clear()
    QUARTER_PAGES.clear()
    if NEWEST:
        for p in hist_periods():
            sm = market.quarter_summary(entries, p)
            if sm:
                SUMMARIES[p] = sm
                QUARTER_PAGES.append(p)
    STOCK_PAGES.clear()
    STOCK_PAGES.update(market.pick_stocks(stocks))
    if NEWEST in SUMMARIES:      # 홈과 최신 분기 요약에 나오는 종목은 눌러서 들어갈 수 있어야 한다
        ls = summary_lists(SUMMARIES[NEWEST])
        shown = [s["ticker"] for k in ("bought", "sold", "held") for s in ls[k]]
        shown += [mv[2]["ticker"] for k in ("big_buys", "big_sells") for mv in ls[k]]
        STOCK_PAGES.update(t for t in shown if t in stocks)

    pages, urls = 0, []

    def emit(lang_root: str, rel: str, url: str, text: str) -> None:
        nonlocal pages
        write(os.path.join(lang_root, rel, "index.html"), text)
        urls.append(url)
        pages += 1

    for lang in LANGS:
        set_lang(lang)
        out_root = os.path.join(SITE, PREFIX[lang].strip("/"))
        emit(out_root, "", PREFIX[lang] + "/", render_home(entries))
        for x in entries:
            m, quarters = x["m"], x["quarters"]
            for i, q in enumerate(quarters):
                sub = "" if i == len(quarters) - 1 else qslug(q["period"])
                emit(out_root, os.path.join("whales", m["slug"], sub),
                     whale_url(m, q["period"], quarters[-1]["period"]), render_whale(m, quarters, i))
        if NEWEST:
            emit(out_root, "stocks", PREFIX[lang] + "/stocks/", render_stocks_index(stocks))
            for t in sorted(STOCK_PAGES):
                emit(out_root, os.path.join("stocks", stock_slug(t)), stock_url(t), render_stock(stocks[t], entries))
        for p in QUARTER_PAGES:
            emit(out_root, os.path.join("quarters", qslug(p)), quarter_url(p), render_quarter(SUMMARIES[p]))
        emit(out_root, "guide", PREFIX[lang] + "/guide/", render_guide(entries))

    # 미리보기 그림은 글자가 영문뿐이라 언어와 상관없이 한 벌만 만든다.
    for x in entries:
        if x["quarters"]:
            q = x["quarters"][-1]
            write_bytes(os.path.join(SITE, og_path(f"{x['m']['slug']}-{qslug(q['period'])}").lstrip("/")),
                        og_whale(x["m"], q))
    write_bytes(os.path.join(SITE, og_path(f"site-{qslug(NEWEST)}" if NEWEST else "site").lstrip("/")),
                og_site(stocks, len(live)))

    write(os.path.join(SITE, "sitemap.xml"),
          '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{SITE_URL}{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    write(os.path.join(SITE, "build.txt"), f"inputs {inputs_digest()}\n")
    have = sum(1 for x in entries if x["quarters"])
    print(f"built {pages} pages in {len(LANGS)} languages  ({have}/{len(managers)} managers with data, "
          f"{len(STOCK_PAGES)} stock pages, {len(QUARTER_PAGES)} quarter summaries)")
    if SUSPECTS:
        # 확인하면 pipeline/splits.json에 옮겨 적는다. 그 전까지는 매매처럼 계산된다.
        todo = ", ".join(f"{t} {p} ~{market.split_label(k)}" for (t, p), k in sorted(SUSPECTS.items(), key=lambda kv: (kv[0][1], kv[0][0])))
        print(f"unconfirmed split suspects ({len(SUSPECTS)}): {todo}")
    if RENAMES:
        # 같은 종목이면 pipeline/ticker_map.json에서 옛 CUSIP을 새 티커로 잇는다.
        todo = ", ".join(f"{old} -> {t} {p} ({n} whales)" for (t, p), (old, n) in sorted(RENAMES.items(), key=lambda kv: (kv[0][1], kv[0][0])))
        print(f"identifier change suspects ({len(RENAMES)}): {todo}")


if __name__ == "__main__":
    main()
