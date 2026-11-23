#!/usr/bin/env python3
"""정적 사이트 생성기.

data/raw/<slug>/<period>/{holdings,meta}.json 스냅샷을 읽어 site/ 아래에
완성된 HTML을 만든다. 브라우저에서 도는 스크립트는 없다. 차트는 전부
빌드할 때 계산한 CSS 상자다. 표준 라이브러리만 쓴다.

  python sitegen/build.py            # site/ 전체 생성
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
SITE = os.path.join(ROOT, "site")
SITE_NAME = "큰손 포트폴리오"
SITE_URL = "https://whaleportfolio.com"   # 대표 주소. www로 들어와도 검색엔진에는 이 주소를 알린다.
# 예전 사이트(ChatGPT Sites 시절)의 주소. 북마크나 검색으로 들어오면 홈으로 보낸다.
OLD_PATHS = ("/dashboard", "/portfolio", "/consensus", "/advertising")
MINUS = "−"
MAX_TABLE_ROWS = 100
MAX_MOVES = 10

e = html.escape


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

    예전 스냅샷에는 티커 자리에 CUSIP이 그대로 든 행이 섞여 있다. 같은 종목이
    분기마다 다른 키로 잡히면 신규·청산으로 잘못 보이므로 여기서 통일한다.
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


def diff(cur: dict, prev: dict | None) -> dict | None:
    """직전 분기와 비교해 cur의 각 행에 상태를 붙이고, 움직임 요약을 돌려준다.

    추정 금액은 주식 수 변화에 이번 분기 말 가격(평가액 / 주식 수)을 곱한 값이다.
    청산은 전분기 말 평가액을 쓴다. 13F에는 실제 거래 가격이 없다.
    """
    if prev is None:
        for r in cur["rows"]:
            r.update(st="base", pct=None, d=0, est=0)
        return None
    pb = {r["key"]: r for r in prev["rows"]}
    buys, sells = [], []
    for r in cur["rows"]:
        p = pb.get(r["key"])
        px = r["value"] / r["shares"] if r["shares"] else 0
        if p is None:
            r.update(st="new", pct=None, d=r["shares"], est=r["value"])
            buys.append(r)
            continue
        d = r["shares"] - p["shares"]
        if d == 0:
            r.update(st="keep", pct=0.0, d=0, est=0)
            continue
        r.update(st="add" if d > 0 else "trim",
                 pct=(d / p["shares"] * 100 if p["shares"] else None),
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
    if r["st"] == "new":
        return "신규"
    if r["st"] == "exit":
        return "청산"
    if r["st"] == "keep":
        return "유지"
    if r["st"] == "base" or r["pct"] is None:
        return "—"
    p = r["pct"]
    if abs(p) >= 1000:
        return f"{'+' if p > 0 else MINUS}{abs(p):,.0f}%"
    return f"{'+' if p > 0 else MINUS}{abs(p):.1f}%"


def tone(r: dict) -> str:
    return {"new": "up", "add": "up", "trim": "dn", "exit": "dn"}.get(r["st"], "nt")


def tk_txt(r: dict) -> str:
    """티커 자리에 쓸 짧은 이름. 티커를 모르면 발행사 이름 앞부분을 쓴다."""
    base = r["ticker"] if r["mapped"] else nice(r["name"])[:18]
    return base + {"PUT": " 풋", "CALL": " 콜"}.get(r["opt"], "")


def nice(name: str) -> str:
    return name.title() if name.isupper() else name


def name_txt(r: dict, ko: dict) -> str:
    if r["mapped"]:
        return ko.get(r["ticker"]) or nice(r["name"])
    return f"CUSIP {r['cusip'] or r['ticker']}"


def w_txt(w: float) -> str:
    return "0.1% 미만" if 0 < w < 0.05 else f"{w:.1f}%"


# ------------------------------------------------------------------ 조각

def page(title: str, desc: str, body: str, path: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE_URL}{path}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&amp;display=swap">
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="/">{SITE_NAME}</a>
<nav aria-label="주 메뉴"><a href="/" aria-current="page">큰손</a></nav>
</div></header>
<main class="wrap">
{body}
<footer>
<p>출처는 미국 SEC EDGAR의 Form 13F-HR입니다. 13F에는 분기 말 미국 상장 주식 보유분만 들어가고, 공매도와 현금, 대부분의 해외 주식은 빠집니다. 공시는 분기가 끝나고 최대 45일 뒤에 나옵니다. 투자 권유가 아닙니다.</p>
<a href="/privacy">개인정보 처리방침</a>
</footer>
</main>
</body>
</html>
"""


def treemap_html(q: dict, ko: dict) -> tuple[str, int]:
    rows = q["rows"]
    main = [r for r in rows if r["w"] >= 0.45][:30]
    rest = rows[len(main):]
    rest_share = sum(r["w"] for r in rest)
    items = [(r, r["value"]) for r in main]
    W, H = 760.0, 520.0
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
            share = sum(t["w"] for t in rest)
            label = f"기타 {len(rest)}개"
            inner = ""
            if tier in ("xl", "lg", "md", "sm"):
                inner = f'<span class="tk">{label}</span><span class="wt">{share:.1f}%</span>'
            elif tier == "xs":
                inner = f'<span class="tk">기타</span>'
            tiles.append(f'<div class="tile etc t-{tier}" style="{pos}" title="{label} · 합계 {share:.1f}%">{inner}</div>')
            continue
        moved = r["st"] in ("new", "add", "trim")
        cls = "s-nt"
        if moved:
            soft = r["st"] != "new" and r["pct"] is not None and abs(r["pct"]) < 5
            cls = "s-" + tone(r) + ("2" if soft else "")
        chg = f'<span class="ch">{pct_txt(r)}</span>' if moved else ""
        wt = f'<span class="wt">{r["w"]:.1f}%</span>'
        label = tk_txt(r) if r["mapped"] else (nice(r["name"]).split() or ["?"])[0][:12]
        tk = f'<span class="tk">{e(label)}</span>'
        nm = f'<span class="nm">{e(name_txt(r, ko) if r["mapped"] else nice(r["name"]))}</span>'
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
        tip = f"{tk_txt(r)} {name_txt(r, ko)} · {r['w']:.1f}% · {pct_txt(r)}"
        tiles.append(f'<div class="tile {cls} t-{tier}" style="{pos}" title="{e(tip)}">{inner}</div>')
    return "\n".join(tiles), len(rest)


def moves_html(title: str, cls: str, rows: list[dict], total: float, sign: str) -> str:
    if not rows:
        return (f'<div class="mv"><div class="mvh {cls}"><h2>{title} 0</h2></div>'
                f'<p class="note">이번 분기에는 없습니다.</p></div>')
    li = "\n".join(
        f'<li><span class="n tk">{e(tk_txt(r))}</span>'
        f'<span class="n pc {cls}">{pct_txt(r)}</span>'
        f'<span class="n est">{usd_est(r["est"], sign)}</span></li>'
        for r in rows[:MAX_MOVES])
    more = f'<p class="note">금액이 작은 {len(rows) - MAX_MOVES}건은 여기에 싣지 않았습니다.</p>' if len(rows) > MAX_MOVES else ""
    return (f'<div class="mv"><div class="mvh {cls}"><h2>{title} {len(rows)}</h2>'
            f'<span class="n">추정 {usd_est(total, sign)}</span></div>\n<ul>\n{li}\n</ul>{more}</div>')


def table_rows(rows: list[dict], ko: dict, wmax: float) -> str:
    out = []
    for r in rows:
        t = tone(r)
        out.append(
            f'<tr><th scope="row"><div class="tkc"><span class="n tk">{e(tk_txt(r))}</span>'
            f'<span class="nm">{e(name_txt(r, ko))}</span></div></th>'
            f'<td><div class="wcell"><span class="bar"><i style="width:{r["w"] / wmax * 100:.1f}%"></i></span>'
            f'<span class="n">{w_txt(r["w"])}</span></div></td>'
            f'<td class="n r">{usd_tbl(r["value"])}</td>'
            f'<td class="n r mt">{r["shares"]:,}</td>'
            f'<td class="n r {t}">{pct_txt(r)}</td></tr>')
    return "\n".join(out)


COLS = ('<colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"></colgroup>')


def holdings_html(q: dict, ko: dict) -> str:
    rows = q["rows"]
    wmax = (rows[0]["w"] if rows else 0) or 1
    head = ('<thead><tr><th scope="col">종목</th><th scope="col">비중</th><th scope="col" class="r">평가액</th>'
            '<th scope="col" class="r">보유 주식 수</th><th scope="col" class="r">이번 분기</th></tr></thead>')
    first, rest = rows[:10], rows[10:MAX_TABLE_ROWS]
    out = [f'<div class="scroll"><table>{COLS}{head}<tbody>\n{table_rows(first, ko, wmax)}\n</tbody></table></div>']
    if rest:
        share = sum(r["w"] for r in rows[10:])
        out.append(
            f'<details><summary>나머지 {len(rows) - 10}개 종목 펼치기 · 합계 {share:.1f}%</summary>'
            f'<div class="scroll"><table>{COLS}<tbody>\n{table_rows(rest, ko, wmax)}\n</tbody></table></div>')
        if len(rows) > MAX_TABLE_ROWS:
            out.append(f'<p class="note">비중이 큰 {MAX_TABLE_ROWS}개까지만 표시했습니다. 전체는 {len(rows):,}개입니다.</p>')
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
            cols.append(f'<div class="col gap"><div class="plot"><span>자료 없음</span></div>'
                        f'<div class="ql n">{qshort(p)}</div><div class="qn">—</div></div>')
            continue
        q = by[p]
        cur = ' aria-current="true"' if p == quarters[idx]["period"] else ""
        cols.append(
            f'<a class="col" href="{whale_url(m, p, latest)}"{cur}><div class="plot">'
            f'<span class="n">${q["total"] / 1e9:.0f}B</span>'
            f'<i style="height:{q["total"] / top * 160:.0f}px"></i></div>'
            f'<div class="ql n">{qshort(p)}</div><div class="qn">{len(q["rows"]):,}개</div></a>')
    return "\n".join(cols)


def whale_url(m: dict, period: str, latest: str) -> str:
    base = f"/whales/{m['slug']}/"
    return base if period == latest else f"{base}{qslug(period)}/"


def switcher_html(m: dict, quarters: list[dict], idx: int, latest: str) -> str:
    def arrow(i, label, d):
        svg = f'<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="{d}"/></svg>'
        if 0 <= i < len(quarters):
            p = quarters[i]["period"]
            return f'<a class="sw" href="{whale_url(m, p, latest)}" aria-label="{label} {qlabel(p)}">{svg}</a>'
        return f'<span class="sw off" aria-hidden="true">{svg}</span>'
    return (arrow(idx - 1, "이전 분기", "M10 3 5 8l5 5")
            + f'<span class="sw now n">{qlabel(quarters[idx]["period"])}</span>'
            + arrow(idx + 1, "다음 분기", "m6 3 5 5-5 5"))


# ------------------------------------------------------------------ 페이지

def render_whale(m: dict, quarters: list[dict], idx: int, ko: dict) -> str:
    q = quarters[idx]
    latest = quarters[-1]["period"]
    by = {x["period"]: x for x in quarters}
    prev = by.get(prev_period(q["period"]))
    mv = diff(q, prev)
    rows, meta = q["rows"], q["meta"]
    top10 = sum(r["w"] for r in rows[:10])
    tiles, n_rest = treemap_html(q, ko)

    place = f" · {e(m['place'])}" if m.get("place") else ""
    filed = f" · 공시일 {dot(meta.get('filed', ''))}" if meta.get("filed") else ""
    src = "" if str(meta.get("source", "")).startswith("EDGAR") else " · 임시 데이터(2차 집계 출처)"
    stats = [("공시 총액", usd_head(q["total"])), ("보유 종목", f"{len(rows):,}"),
             ("상위 10개 비중", f"{top10:.1f}%")]
    if mv:
        c = mv["total_chg"]
        stats.append(("전분기 대비", f"{'+' if c >= 0 else MINUS}{abs(c):.1f}%"))
    else:
        stats.append(("전분기 대비", "—"))
    stats_html = "\n".join(f'<div><span>{k}</span><b class="n">{v}</b></div>' for k, v in stats)

    if mv:
        rail = (moves_html("늘림", "up", mv["buys"], mv["buy_total"], "+")
                + moves_html("줄임", "dn", mv["sells"], mv["sell_total"], MINUS)
                + '<p class="note">금액은 주식 수 변화에 분기 말 가격을 곱한 추정치입니다. 청산은 전분기 말 평가액입니다.</p>')
        cap = "면적은 비중, 색은 이번 분기 주식 수 변화입니다."
    else:
        rail = (f'<div class="mv"><p class="note">직전 분기({qlabel(prev_period(q["period"]))}) 자료가 없어 '
                f'이번 분기에 무엇을 사고팔았는지는 계산하지 않았습니다.</p></div>')
        cap = "면적은 비중입니다. 직전 분기 자료가 없어 변화는 색으로 표시하지 않았습니다."
    rest_note = (f'<p class="note">비중이 작은 {n_rest}개 종목은 "기타"로 묶었습니다. 전체는 아래 표에 있습니다.</p>'
                 if n_rest else "")
    ended = f'<p class="ended"><b>공시 종료</b>{e(m.get("ended_note", ""))}</p>' if m.get("status") == "ended" else ""
    if m.get("note"):
        ended += f'<p class="ended"><b>알아둘 점</b>{e(m["note"])}</p>'

    body = f"""
<div class="head">
<div>
<p class="crumb"><a href="/">큰손</a> / {e(m['ko'])}</p>
<h1>{e(m['ko'])}</h1>
<p class="meta">{e(m['en'])}{place} · 기준일 {dot(q['period'])}{filed}{src}</p>
</div>
<div class="switch">{switcher_html(m, quarters, idx, latest)}</div>
</div>
{ended}
<div class="stats">
{stats_html}
</div>
<div class="hero">
<section class="map">
<div class="maph"><h2>포트폴리오 지도</h2>
<div class="legend"><span><i class="up"></i>늘림</span><span><i class="dn"></i>줄임</span><span><i class="nt"></i>그대로</span></div></div>
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
<h2>분기별 흐름</h2>
<p class="cap">공시 총액과 종목 수입니다. 막대를 누르면 그 분기로 갑니다.</p>
<div class="hist">
{history_html(m, quarters, idx, latest)}
</div>
</section>

<section>
<h2>보유 종목</h2>
{holdings_html(q, ko)}
<p class="src"><a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK={int(m['cik']):010d}&amp;type=13F-HR">SEC 원문 보기</a>{' · 접수번호 ' + e(meta['accession']) if meta.get('accession') else ''}</p>
</section>
"""
    title = f"{m['ko']} 포트폴리오 {qlabel(q['period'])} | {SITE_NAME}"
    desc = (f"{m['ko']}의 {qlabel(q['period'])} 13F 공시. 공시 총액 {usd_head(q['total'])}, "
            f"보유 종목 {len(rows):,}개.")
    return page(title, desc, body, whale_url(m, q["period"], latest))


def render_home(entries: list[dict], ko: dict) -> str:
    """entries: {m, quarters, mv} — quarters가 비면 아직 수집 전이다."""
    live = [x for x in entries if x["quarters"]]
    wait = [x for x in entries if not x["quarters"] and x["m"].get("status") != "ended"]
    ended_nodata = [x for x in entries if not x["quarters"] and x["m"].get("status") == "ended"]
    live.sort(key=lambda x: -x["quarters"][-1]["total"])
    newest = max((x["quarters"][-1]["period"] for x in live), default="")

    rows = []
    for x in live:
        m, q, mv = x["m"], x["quarters"][-1], x["mv"]
        top = q["rows"][0]
        chips = ""
        if mv:
            picks = sorted(mv["buys"] + mv["sells"], key=lambda r: -r["est"])[:3]
            kind = {"new": "신규", "add": "확대", "trim": "축소", "exit": "청산"}
            chips = "".join(
                f'<span class="chip"><b class="{tone(r)}">{kind[r["st"]]}</b>'
                f'<span class="n">{e(tk_txt(r))}{"" if r["st"] in ("new", "exit") else " " + pct_txt(r)}</span></span>'
                for r in picks)
        tag = ""
        if m.get("status") == "ended":
            tag = f'<span class="tag">공시 종료 · {qlabel(q["period"])} 기준</span>'
        elif q["period"] != newest:
            tag = f'<span class="tag">{qlabel(q["period"])} 기준</span>'
        person = f" · {e(m['person'])}" if m.get("person") else ""
        rows.append(
            f'<a class="row" href="/whales/{m["slug"]}/">'
            f'<span class="who"><b>{e(m["ko"])}</b>{tag}<small>{e(m["en"])}{person}</small></span>'
            f'<span class="n num">{usd_tbl(q["total"])}</span>'
            f'<span class="n num">{len(q["rows"]):,}</span>'
            f'<span class="topc"><span class="n"><b>{e(tk_txt(top))}</b>{top["w"]:.1f}%</span>'
            f'<span class="bar"><i style="width:{top["w"]:.1f}%"></i></span></span>'
            f'<span class="chips">{chips}</span></a>')
    for x in ended_nodata:
        m = x["m"]
        rows.append(f'<div class="row off"><span class="who"><b>{e(m["ko"])}</b><span class="tag">공시 종료</span>'
                    f'<small>{e(m["en"])} · {e(m.get("person", ""))}</small></span>'
                    f'<span class="endn">{e(m.get("ended_note", ""))}</span></div>')
    waiting = ""
    if wait:
        names = ", ".join(e(x["m"]["ko"]) for x in wait)
        waiting = f'<p class="note wait">첫 수집을 기다리는 곳 {len(wait)}곳: {names}</p>'
    sub = f"{qlabel(newest)} · 기준일 {dot(newest)}" if newest else "아직 수집된 분기가 없습니다"
    body = f"""
<div class="head home">
<div>
<p class="crumb n">{sub}</p>
<h1>큰손들은 이번 분기에<br>무엇을 사고팔았나</h1>
<p class="meta">분기 말 보유 내역을 직전 분기와 비교해 큰손별로 정리했습니다.</p>
</div>
</div>
<div class="scroll">
<div class="list">
<div class="row lh"><span>큰손</span><span class="num">공시 총액</span><span class="num">종목 수</span><span>최대 보유</span><span>이번 분기 주요 움직임</span></div>
{chr(10).join(rows)}
</div>
</div>
{waiting}
"""
    return page(f"{SITE_NAME} — 13F로 보는 큰손들의 분기별 매매",
                "미국 SEC 13F 공시로 큰손들이 분기마다 무엇을 사고팔았는지 큰손별로 정리합니다.", body, "/")


CSS = """
:root{--bg:#0D1117;--sf:#161C25;--ln:#2A323E;--tx:#E8ECF2;--mt:#9BA6B5;--ft:#8793A3;--up:#FF8A4C;--dn:#7AA7FF;--tile:#232B37}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 "Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif}
.n{font-family:"Space Grotesk","Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;font-variant-numeric:tabular-nums}
a{color:inherit}a:hover{color:var(--up)}
h1,h2,p,ul{margin:0}ul{padding:0;list-style:none}
.wrap{max-width:1200px;margin:0 auto;padding:0 32px}
.top{border-bottom:1px solid var(--ln)}
.top .wrap{min-height:64px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:4px 24px}
.brand{font-size:17px;font-weight:700;letter-spacing:-.01em;text-decoration:none;padding:10px 0}
nav a{display:inline-block;padding:11px 14px;font-weight:700;text-underline-offset:6px;text-decoration-thickness:2px}
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
.tm{margin-top:16px;position:relative;width:100%;aspect-ratio:760/520;container-type:inline-size;font-family:"Space Grotesk","Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif}
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
@media (max-width:640px){.wrap{padding:0 16px}h1{font-size:30px}.home h1{font-size:32px}.hist{gap:6px;padding:14px 10px}.col{font-size:11px}.stats b{font-size:20px}}
"""


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main() -> None:
    managers = _json(os.path.join(ROOT, "managers.json"), [])
    tmap = load_tmap()
    ko = _json(os.path.join(HERE, "names_ko.json"), {})

    # 생성물만 지운다. site/privacy.html 같은 손으로 쓴 파일은 그대로 둔다.
    for stale in ("whales", "assets", "data"):
        shutil.rmtree(os.path.join(SITE, stale), ignore_errors=True)
    write(os.path.join(SITE, "assets", "style.css"), CSS.strip() + "\n")

    # Cloudflare Pages는 site/_redirects를 읽는다. 쿼리스트링(?manager=...)은 구분하지 못한다.
    write(os.path.join(SITE, "_redirects"),
          "".join(f"{p} / 301\n{p}/* / 301\n" for p in OLD_PATHS))
    write(os.path.join(SITE, "robots.txt"), f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")

    entries, pages, urls = [], 0, ["/"]
    for m in managers:
        quarters = load_manager(m, tmap)
        latest_mv = None
        for i, q in enumerate(quarters):
            out = render_whale(m, quarters, i, ko)  # diff()가 q의 행에 상태를 붙인다
            is_latest = i == len(quarters) - 1
            sub = "" if is_latest else qslug(q["period"])
            write(os.path.join(SITE, "whales", m["slug"], sub, "index.html"), out)
            urls.append(whale_url(m, q["period"], quarters[-1]["period"]))
            pages += 1
        if quarters:
            by = {x["period"]: x for x in quarters}
            latest_mv = diff(quarters[-1], by.get(prev_period(quarters[-1]["period"])))
        entries.append({"m": m, "quarters": quarters, "mv": latest_mv})
    write(os.path.join(SITE, "index.html"), render_home(entries, ko))
    write(os.path.join(SITE, "sitemap.xml"),
          '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{SITE_URL}{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    have = sum(1 for x in entries if x["quarters"])
    print(f"built {pages + 1} pages  ({have}/{len(managers)} managers with data)")


if __name__ == "__main__":
    main()
