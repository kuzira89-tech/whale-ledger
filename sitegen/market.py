"""큰손 여러 곳을 가로질러 보는 계산.

- 주식 분할 추정: 13F에는 분할 정보가 없어서, 분할이 있던 분기에는 보유자 전원이
  주식을 사들인 것처럼 보인다. 가격과 주식 수가 함께 움직인 모양으로 분할을 가려낸다.
- 종목별 보유 현황: 어느 큰손이 얼마나 들고 있고 이번 분기에 어떻게 했는지.
- 분기 요약: 한 분기에 여러 큰손이 함께 사고판 종목.

HTML은 만들지 않는다. sitegen/build.py가 여기서 나온 값을 화면으로 옮긴다.
"""
from __future__ import annotations

import statistics

MEANINGFUL_PCT = 5.0   # 분기 요약에서 "샀다/팔았다"로 세는 최소 변화율


Q_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def prev_period(period: str) -> str:
    y, m, _ = period.split("-")
    y, q = int(y), (int(m) + 2) // 3
    y, q = (y - 1, 4) if q == 1 else (y, q - 1)
    return f"{y}-{Q_END[q]}"


def split_label(k: float) -> str:
    """분할 비율을 사람이 읽는 꼴로. 10 → 10:1, 1.5 → 3:2, 0.1 → 1:10."""
    for num, den in ((3, 2), (5, 4), (4, 3)):
        if abs(k - num / den) < 1e-6:
            return f"{num}:{den}"
    if k >= 1:
        return f"{k:g}:1"
    return f"1:{1 / k:g}"


def _hold_like(x: float) -> float:
    """주식 수 비율 x가 "평소의 매매"로 얼마나 그럴듯한가. 거의 그대로일수록 높다."""
    d = abs(x - 1)
    if d <= 0.01:
        return 5.0
    if d <= 0.03:
        return 2.0
    return 1.0 if 0.7 <= x <= 1.5 else 0.2


def _price_like(c: float) -> float:
    """한 분기의 가격 변화 c배가 얼마나 그럴듯한가. 반 토막이나 두 배는 드물다."""
    if 0.85 <= c <= 1.2:
        return 1.5
    if 0.6 <= c <= 1.6:
        return 1.0
    return 0.15 if 0.4 <= c <= 2.5 else 0.02


def split_factor(obs: list[tuple[float, float]]) -> float | None:
    """한 종목의 한 분기 관측값 [(주식 수 비율, 가격 비율)]에서 분할 비율을 추정한다.

    분할 비율 k마다 "분할을 걷어 내면 보유자들의 매매와 가격 변화가 평범해 보이는가"를
    점수로 매기고, 분할이 없었다는 가정과 견준다. 분할 쪽이 뚜렷이 앞설 때만 k를 돌려준다.

    - 분할이 있었다면 주식 수가 그대로인 보유자가 있을 수 없다.
    - 보유자들은 분할 분기에도 조금씩 사고팔기 때문에 k배에 딱 맞지 않는 경우가 많다.
    - 2:1, 10:1처럼 흔한 비율을 먼저 믿는다. 6:1, 12:1 같은 비율은 증거가 더 있어야 한다.
    """
    if not obs:
        return None
    pr = statistics.median(p for _, p in obs)
    if 0.72 < pr < 1.6:                       # 가격이 크게 움직이지 않았으면 볼 것도 없다
        return None
    if any(abs(sr - 1) <= 0.002 for sr, _ in obs):
        return None

    def score(k: float, prior: float) -> float:
        s = prior * _price_like(pr * k)
        for sr, _ in obs:
            s *= _hold_like(sr / k)
        return s

    null = score(1.0, 30.0)
    best_k, best = None, 0.0
    for k, prior in SPLIT_PRIORS.items():
        if (k > 1) != (pr < 1):                # 분할이면 가격이 내리고, 병합이면 오른다
            continue
        if k < 1 and sum(1 for sr, _ in obs if abs(sr / k - 1) <= 0.03) < 2:
            continue                           # 병합은 "오른 뒤 절반을 판" 경우와 헷갈린다
        s = score(k, prior)
        if s > best:
            best_k, best = k, s
    if best_k is None or best < 5 * null:
        return None
    if not any(abs(sr / best_k - 1) <= 0.15 for sr, _ in obs):
        return None
    return best_k


# 분할 비율 → 얼마나 흔한가. 병합(1:k)은 드물어서 낮게 둔다.
SPLIT_PRIORS = {2: 10, 3: 6, 4: 5, 5: 5, 10: 5, 20: 3, 1.5: 3, 15: 1, 25: 1, 8: 0.7,
                6: 0.5, 7: 0.5, 1.25: 0.5, 4 / 3: 0.5, 12: 0.3, 30: 0.3, 40: 0.3, 50: 0.3,
                1 / 2: 0.3, 1 / 3: 0.3, 1 / 4: 0.3, 1 / 5: 0.3, 1 / 10: 0.3, 1 / 20: 0.3}


def pinned_splits(raw: dict) -> tuple[dict[tuple[str, str], float], set[tuple[str, str]]]:
    """pipeline/splits.json을 읽는다. (확인된 분할, 분할이 아니라고 확인한 것)을 돌려준다.

    계산에는 확인된 분할만 쓴다. 추정은 비율을 자주 틀려서(4:1을 3:1로 읽는 식이다)
    숫자를 고치는 데 쓰면 그럴듯하게 틀린 값이 나온다.
    """
    pinned = {(s["ticker"], s["period"]): float(s["ratio"]) for s in raw.get("splits", [])}
    vetoed = {(s["ticker"], s["period"]) for s in raw.get("not_splits", [])}
    return pinned, vetoed


def find_splits(entries: list[dict]) -> dict[tuple[str, str], float]:
    """(티커, 분기) → 추정한 분할 비율. 그 분기에 주식 분할이 있었다고 볼 만한 종목만 담는다.

    추정일 뿐이다. 확인해서 pipeline/splits.json에 옮겨 적기 전에는 계산에 쓰지 않는다.
    """
    obs: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for x in entries:
        by = {q["period"]: q for q in x["quarters"]}
        for q in x["quarters"]:
            p = by.get(prev_period(q["period"]))
            if not p:
                continue
            pb = {r["key"]: r for r in p["rows"]}
            for r in q["rows"]:
                o = pb.get(r["key"])
                if r["opt"] or not o or min(o["shares"], r["shares"], o["value"], r["value"]) <= 0:
                    continue
                sr = r["shares"] / o["shares"]
                pr = (r["value"] / r["shares"]) / (o["value"] / o["shares"])
                obs.setdefault((r["ticker"], q["period"]), []).append((sr, pr))
    out = {}
    for key, lst in obs.items():
        k = split_factor(lst)
        if k:
            out[key] = k
    return out


# ------------------------------------------------------------------ 식별 번호가 바뀐 종목

_NOISE = {"INC", "CORP", "LTD", "CO", "PLC", "THE", "HLDGS", "HOLDINGS", "GROUP", "SA", "NV", "AG", "ADR",
          "SPONSORED", "ADS", "CL", "A", "B", "COM", "NEW", "LIMITED", "CORPORATION", "COMPANY", "INDS",
          "INDUSTRIES", "DEL", "USA"}


def issuer_key(name: str) -> str:
    """발행사 이름에서 회사 형태 같은 군말을 떼고 앞 두 단어만 남긴다."""
    words = [w for w in "".join(c if c.isalnum() else " " for c in name.upper()).split() if w not in _NOISE]
    return " ".join(words[:2])


def find_renames(entries: list[dict]) -> dict[tuple[str, str], tuple[str, int]]:
    """(새 티커, 분기) → (옛 키, 큰손 수). 식별 번호(CUSIP)가 바뀐 것으로 보이는 종목이다.

    회사가 본사를 옮기거나 주식을 병합하면 CUSIP이 바뀐다. 그러면 같은 종목인데도
    "옛 종목 청산 + 새 종목 신규"로 보인다. 같은 분기에 두 곳 이상이 같은 발행사 이름으로
    그런 짝을 보이면 의심한다. 확인되면 pipeline/ticker_map.json에서 옛 CUSIP을 새 티커로 잇는다.

    같은 운용사의 다른 ETF(iShares끼리)를 갈아탄 경우를 거르려고, 옛 쪽이 티커 없는 CUSIP이거나
    두 티커의 앞 세 글자가 같을 때만 본다.
    """
    seen: dict[tuple[str, str, str], int] = {}
    for x in entries:
        for q in x["quarters"]:
            mv = q.get("mv")
            if not mv:
                continue
            gone: dict[str, list[dict]] = {}
            for r in mv["sells"]:
                if r["st"] == "exit" and not r["opt"]:
                    gone.setdefault(issuer_key(r["name"]), []).append(r)
            for r in mv["buys"]:
                if r["st"] != "new" or r["opt"] or not r["mapped"]:
                    continue
                for o in gone.get(issuer_key(r["name"]), []):
                    if o["ticker"] != r["ticker"] and (not o["mapped"] or o["ticker"][:3] == r["ticker"][:3]):
                        k = (r["ticker"], q["period"], o["key"])
                        seen[k] = seen.get(k, 0) + 1
    return {(t, p): (old, n) for (t, p, old), n in seen.items() if n >= 2}


# ------------------------------------------------------------------ 종목별 보유 현황

def collect_stocks(entries: list[dict]) -> dict[str, dict]:
    """티커 → {ticker, name, holders, opts, exits}.

    각 큰손의 가장 최근 분기를 본다. 공시를 끝낸 곳은 자료가 오래돼 뺀다.
    holders는 주식 보유, opts는 풋·콜, exits는 그 분기에 전부 판 곳이다.
    항목은 {m, q, r, rank}이고 r에는 diff()가 붙인 상태(st, pct …)가 들어 있다.
    """
    stocks: dict[str, dict] = {}

    def slot(r):
        return stocks.setdefault(r["ticker"], {"ticker": r["ticker"], "name": r["name"],
                                               "holders": [], "opts": [], "exits": []})

    for x in entries:
        m, qs = x["m"], x["quarters"]
        if not qs or m.get("status") == "ended":
            continue
        q = qs[-1]
        for rank, r in enumerate(q["rows"], 1):
            if r["mapped"]:
                slot(r)["opts" if r["opt"] else "holders"].append({"m": m, "q": q, "r": r, "rank": rank})
        for r in (q.get("mv") or {}).get("sells", []):
            if r["st"] == "exit" and r["mapped"] and not r["opt"]:
                slot(r)["exits"].append({"m": m, "q": q, "r": r, "rank": 0})
    for s in stocks.values():
        s["holders"].sort(key=lambda h: -h["r"]["value"])
        s["value"] = sum(h["r"]["value"] for h in s["holders"])
    return stocks


def pick_stocks(stocks: dict[str, dict], top_n: int = 25, min_holders: int = 3) -> set[str]:
    """전용 페이지를 만들 종목. 여러 곳이 들고 있거나, 어느 한 곳의 상위권에 있는 종목이다."""
    keep = {t for t, s in stocks.items() if len(s["holders"]) >= min_holders}
    keep |= {t for t, s in stocks.items() if any(h["rank"] <= top_n for h in s["holders"])}
    return keep


def stock_history(entries: list[dict], ticker: str, periods: list[str]) -> list[dict]:
    """종목 하나를 큰손 × 분기로 펼친다. 기간 안에 한 번이라도 들고 있던 곳만 돌려준다.

    칸은 None(그 분기 자료 없음), {"st": "none"}(자료는 있고 보유하지 않음),
    또는 보유·청산 행(st, pct, w …)이다.
    """
    out = []
    for x in entries:
        by = {q["period"]: q for q in x["quarters"]}
        cells, held = [], False
        for p in periods:
            q = by.get(p)
            if q is None:
                cells.append(None)
                continue
            r = next((r for r in q["rows"] if r["ticker"] == ticker and r["mapped"] and not r["opt"]), None)
            if r is None:
                r = next((s for s in (q.get("mv") or {}).get("sells", [])
                          if s["st"] == "exit" and s["ticker"] == ticker and s["mapped"] and not s["opt"]), None)
            if r is None:
                cells.append({"st": "none"})
            else:
                held = True
                cells.append(r)
        if held:
            out.append({"m": x["m"], "cells": cells})
    out.sort(key=lambda row: -max((c.get("value", 0) for c in row["cells"] if c and c["st"] != "exit"), default=0))
    return out


# ------------------------------------------------------------------ 분기 요약

def meaningful(r: dict) -> bool:
    """주식 수를 눈에 띄게 바꿨는가. 신규·청산은 항상, 그 밖에는 5% 이상일 때."""
    if r["st"] in ("new", "exit"):
        return True
    return r["pct"] is None or abs(r["pct"]) >= MEANINGFUL_PCT


def quarter_summary(entries: list[dict], period: str) -> dict | None:
    """한 분기에 큰손들이 함께 사고판 종목을 모은다.

    직전 분기 자료까지 있는 큰손만 "움직임"에 넣는다. 연금처럼 종목이 수백 개인 곳은
    거의 모든 종목을 조금씩 조정하므로, 5% 이상 바꾼 경우만 샀다/팔았다로 센다.
    """
    per: dict[str, dict] = {}
    whales, moves = [], []

    def slot(r):
        return per.setdefault(r["ticker"], {"ticker": r["ticker"], "name": r["name"], "r": r,
                                            "hold": [], "buy": [], "sell": []})

    for x in entries:
        q = next((q for q in x["quarters"] if q["period"] == period), None)
        if q is None:
            continue
        for r in q["rows"]:
            if r["mapped"] and not r["opt"]:
                slot(r)["hold"].append((x["m"], r))
        mv = q.get("mv")
        if not mv:
            continue
        whales.append(x["m"])
        for side, rows in (("buy", mv["buys"]), ("sell", mv["sells"])):
            for r in rows:
                if not r["mapped"] or r["opt"]:
                    continue
                moves.append((side, x["m"], r))
                if meaningful(r):
                    slot(r)[side].append((x["m"], r))
    if len(whales) < 5:
        return None

    def est(pairs):
        return sum(r["est"] for _, r in pairs)

    items = list(per.values())
    for s in items:
        s["buy"].sort(key=lambda mr: -mr[1]["est"])
        s["sell"].sort(key=lambda mr: -mr[1]["est"])
    bought = sorted((s for s in items if len(s["buy"]) >= 2), key=lambda s: (-len(s["buy"]), -est(s["buy"])))
    sold = sorted((s for s in items if len(s["sell"]) >= 2), key=lambda s: (-len(s["sell"]), -est(s["sell"])))
    held = sorted(items, key=lambda s: (-len(s["hold"]), -sum(r["value"] for _, r in s["hold"])))
    return {
        "period": period, "whales": whales,
        "bought": bought, "sold": sold, "held": [s for s in held if len(s["hold"]) >= 2],
        "big_buys": sorted((mv for mv in moves if mv[0] == "buy"), key=lambda mv: -mv[2]["est"]),
        "big_sells": sorted((mv for mv in moves if mv[0] == "sell"), key=lambda mv: -mv[2]["est"]),
    }
