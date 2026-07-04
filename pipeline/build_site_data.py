"""Turn per-period holdings snapshots into the site's data.js.

Input : data/raw/<period>/holdings.json  (compact rows) + meta.json
Output: site/data/data.js  ->  window.WHALE_DATA = {...}

The compact holdings row is [ticker, name, class, shares, value]. Diffing is
done on TICKER (not CUSIP) so a position stays continuous even when its CUSIP
changes on a corporate reorganization (e.g. the 2025 Liberty Live split).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
OUT_JS = os.path.join(ROOT, "site", "data", "data.js")
SUPP_JSON = os.path.join(ROOT, "data", "supplemental.json")

MANAGER = {
    "cik": 1067983,
    "name": "Berkshire Hathaway Inc",
    "person": "Warren Buffett",
    "label": {"ko": "버크셔 해서웨이 (워런 버핏)",
              "ja": "バークシャー・ハサウェイ (ウォーレン・バフェット)",
              "en": "Berkshire Hathaway (Warren Buffett)"},
}

LANGS = ("ko", "ja", "en")
DRIFT_WARN = 0.005  # 0.5% tolerance between summed value and reported total


# ---------------------------------------------------------------- loading ----

def _load_period(period: str) -> dict[str, Any] | None:
    pdir = os.path.join(RAW_DIR, period)
    hfile = os.path.join(pdir, "holdings.json")
    mfile = os.path.join(pdir, "meta.json")
    if not os.path.exists(hfile):
        return None
    with open(hfile, encoding="utf-8") as f:
        hjson = json.load(f)
    meta = {}
    if os.path.exists(mfile):
        with open(mfile, encoding="utf-8") as f:
            meta = json.load(f)
    rows = hjson.get("holdings", [])
    holdings = []
    for row in rows:
        ticker, name, cl, shares, value = (list(row) + ["", "", "", 0, 0])[:5]
        holdings.append({
            "key": ticker,
            "ticker": ticker,
            "name": name,
            "cl": cl,
            "shares": int(shares),
            "value": int(value),
        })
    return {"period": period, "meta": meta, "holdings": holdings}


def _discover_periods() -> list[str]:
    if not os.path.isdir(RAW_DIR):
        return []
    periods = [d for d in os.listdir(RAW_DIR)
               if os.path.isdir(os.path.join(RAW_DIR, d)) and d[:4].isdigit()]
    periods.sort(reverse=True)  # newest first
    return periods


def _load_supplemental():
    """Load the manually-maintained off-13F data (Japanese stakes, cash, bonds).
    Returns None if the file is absent so the site simply omits that section."""
    if not os.path.exists(SUPP_JSON):
        return None
    with open(SUPP_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ---------------------------------------------------------------- format -----

def _eok(value: int) -> float:
    """Dollars -> 억/億 units (1e8), rounded to 1 decimal."""
    return round(value / 1e8, 1)


def _fmt_eok(value: int, lang: str) -> str:
    if lang == "en":
        if abs(value) >= 1e9:
            return f"${value / 1e9:,.1f}B"
        if abs(value) >= 1e6:
            return f"${value / 1e6:,.0f}M"
        return f"${value:,}"
    n = _eok(value)
    s = f"{n:,.1f}"
    return f"{s}억 달러" if lang == "ko" else f"{s}億ドル"


def _fmt_pct(p: float) -> str:
    sign = "+" if p > 0 else ""
    return f"{sign}{p:.0f}%"


def _period_label(period: str, lang: str) -> str:
    y, m, _ = period.split("-")
    q = {"03": 1, "06": 2, "09": 3, "12": 4}.get(m, 0)
    if lang == "ko":
        return f"{y}년 {q}분기"
    if lang == "ja":
        return f"{y}年 Q{q}"
    return f"Q{q} {y}"


def _short_name(rec: dict, lang: str) -> str:
    """A compact issuer label for prose (ticker-first keeps it stable)."""
    cl = rec.get("cl", "")
    tag = f" {cl}" if cl and cl not in ("", "COM") else ""
    return f"{rec['ticker']}{tag}"


# ---------------------------------------------------------------- diffing ----

def _diff(cur: list[dict], prev: list[dict] | None):
    total = sum(h["value"] for h in cur) or 1
    prev_by = {h["ticker"]: h for h in (prev or [])}
    cur_tickers = {h["ticker"] for h in cur}
    out = []
    stats = {"new": 0, "added": 0, "trimmed": 0, "kept": 0, "exited": 0}
    for h in cur:
        rec = dict(h)
        rec["weight"] = round(h["value"] / total * 100, 2)
        if prev is None:
            rec.update(prev_shares=None, delta_shares=None, pct_chg=None, status="HOLD")
        elif h["ticker"] not in prev_by:
            rec.update(prev_shares=0, delta_shares=h["shares"], pct_chg=None, status="NEW")
            stats["new"] += 1
        else:
            ps = prev_by[h["ticker"]]["shares"]
            ds = h["shares"] - ps
            pct = (ds / ps * 100) if ps else None
            if ds > 0:
                status = "ADD"; stats["added"] += 1
            elif ds < 0:
                status = "TRIM"; stats["trimmed"] += 1
            else:
                status = "KEEP"; stats["kept"] += 1
            rec.update(prev_shares=ps, delta_shares=ds,
                       pct_chg=(round(pct, 1) if pct is not None else None),
                       status=status)
        out.append(rec)
    out.sort(key=lambda r: r["value"], reverse=True)

    exits = []
    if prev is not None:
        for t, h in prev_by.items():
            if t not in cur_tickers:
                exits.append({"ticker": t, "name": h["name"], "cl": h["cl"],
                              "shares": h["shares"], "value": h["value"]})
        exits.sort(key=lambda r: r["value"], reverse=True)
        stats["exited"] = len(exits)
    return out, exits, stats


# --------------------------------------------------------------- summaries ---

def _join(items: list[str], lang: str) -> str:
    sep = "、" if lang == "ja" else ", "
    return sep.join(items)


def _make_summary(holdings: list[dict], exits: list[dict], stats: dict,
                  total: int, prev_total: int | None, lang: str) -> str:
    # base quarter: no prior period to compare against
    if all(h.get("status") == "HOLD" for h in holdings):
        n = len(holdings)
        if lang == "ko":
            return (f"기준 분기. 총 {n}개 종목, 평가액 {_fmt_eok(total, 'ko')}. "
                    f"이전 분기 데이터가 없어 증감은 표시하지 않음.")
        if lang == "ja":
            return (f"基準四半期。全{n}銘柄、評価額 {_fmt_eok(total, 'ja')}。"
                    f"前四半期のデータがないため増減は表示なし。")
        return (f"Base quarter. {n} holdings, {_fmt_eok(total, 'en')} total. "
                f"No prior-quarter data, so changes are not shown.")

    news = sorted([h for h in holdings if h["status"] == "NEW"],
                  key=lambda r: r["value"], reverse=True)
    adds = sorted([h for h in holdings if h["status"] == "ADD" and h.get("pct_chg") is not None],
                  key=lambda r: r["pct_chg"], reverse=True)
    trims = sorted([h for h in holdings if h["status"] == "TRIM" and h.get("pct_chg") is not None],
                   key=lambda r: r["pct_chg"])
    chg = ((total - prev_total) / prev_total * 100) if prev_total else None

    parts: list[str] = []
    moves: list[str] = []

    if lang == "ko":
        if news:
            parts.append(f"신규 {stats['new']}종목({_join([_short_name(h, 'ko') for h in news[:3]], 'ko')})")
        if stats["exited"]:
            more = " 외" if stats["exited"] > 3 else ""
            parts.append(f"전량매도 {stats['exited']}종목({_join([e['ticker'] for e in exits[:3]], 'ko')}{more})")
        if adds:
            moves.append(f"{_short_name(adds[0], 'ko')} {_fmt_pct(adds[0]['pct_chg'])} 증액")
        if trims:
            moves.append(f"{_short_name(trims[0], 'ko')} {_fmt_pct(trims[0]['pct_chg'])} 축소")
        s = "이번 분기: " + _join(parts, "ko") + ("." if parts else "")
        if moves:
            s += " 최대 변동은 " + _join(moves, "ko") + "."
        s += (f" 총 평가액 {_fmt_eok(total, 'ko')}(전분기 대비 {_fmt_pct(chg)})."
              if chg is not None else f" 총 평가액 {_fmt_eok(total, 'ko')}.")
        return s

    if lang == "ja":
        if news:
            parts.append(f"新規{stats['new']}銘柄({_join([_short_name(h, 'ja') for h in news[:3]], 'ja')})")
        if stats["exited"]:
            more = "ほか" if stats["exited"] > 3 else ""
            parts.append(f"全売却{stats['exited']}銘柄({_join([e['ticker'] for e in exits[:3]], 'ja')}{more})")
        if adds:
            moves.append(f"{_short_name(adds[0], 'ja')} {_fmt_pct(adds[0]['pct_chg'])}増")
        if trims:
            moves.append(f"{_short_name(trims[0], 'ja')} {_fmt_pct(trims[0]['pct_chg'])}減")
        s = "今四半期：" + _join(parts, "ja") + ("。" if parts else "")
        if moves:
            s += "最大の変動は" + _join(moves, "ja") + "。"
        s += (f"評価額合計 {_fmt_eok(total, 'ja')}(前四半期比 {_fmt_pct(chg)})。"
              if chg is not None else f"評価額合計 {_fmt_eok(total, 'ja')}。")
        return s

    # English
    if news:
        parts.append(f"{stats['new']} new ({_join([_short_name(h, 'en') for h in news[:3]], 'en')})")
    if stats["exited"]:
        more = " +more" if stats["exited"] > 3 else ""
        parts.append(f"{stats['exited']} sold out ({_join([e['ticker'] for e in exits[:3]], 'en')}{more})")
    if adds:
        moves.append(f"{_short_name(adds[0], 'en')} {_fmt_pct(adds[0]['pct_chg'])}")
    if trims:
        moves.append(f"{_short_name(trims[0], 'en')} {_fmt_pct(trims[0]['pct_chg'])}")
    s = "This quarter: " + _join(parts, "en") + ("." if parts else "")
    if moves:
        s += " Biggest moves: " + _join(moves, "en") + "."
    s += (f" Total value {_fmt_eok(total, 'en')} ({_fmt_pct(chg)} QoQ)."
          if chg is not None else f" Total value {_fmt_eok(total, 'en')}.")
    return s


# ----------------------------------------------------------------- build -----

def build(verbose: bool = True) -> dict:
    periods = _discover_periods()
    loaded = [p for p in (_load_period(x) for x in periods) if p]
    if not loaded:
        raise SystemExit("no period data found under data/raw/")

    loaded_oldest_first = list(reversed(loaded))
    quarters = []
    for i, cur in enumerate(loaded_oldest_first):
        prev = loaded_oldest_first[i - 1]["holdings"] if i > 0 else None
        prev_total = sum(h["value"] for h in loaded_oldest_first[i - 1]["holdings"]) if i > 0 else None
        holdings, exits, stats = _diff(cur["holdings"], prev)
        total = sum(h["value"] for h in cur["holdings"])
        meta = cur["meta"]
        reported = int(meta.get("total_value", 0) or 0)
        if reported and abs(total - reported) / reported > DRIFT_WARN and verbose:
            drift = (total - reported) / reported * 100
            print(f"  ! {cur['period']}: summed {total:,} vs reported {reported:,} "
                  f"({drift:+.2f}% drift)")
        summary = {lg: _make_summary(holdings, exits, stats, total, prev_total, lg)
                   for lg in LANGS}
        quarters.append({
            "period": cur["period"],
            "label": {lg: _period_label(cur["period"], lg) for lg in LANGS},
            "filed": meta.get("filed", ""),
            "form": meta.get("form", "13F-HR"),
            "accession": meta.get("accession", ""),
            "source": meta.get("source", ""),
            "total_value": total,
            "reported_total": reported or total,
            "num_holdings": len(holdings),
            "stats": stats,
            "holdings": holdings,
            "exits": exits,
            "summary": summary,
        })

    quarters.sort(key=lambda q: q["period"], reverse=True)  # newest first
    return {
        "manager": MANAGER,
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "quarters": quarters,
        "supplemental": _load_supplemental(),
    }


def write_js(data: dict, path: str = OUT_JS) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("// AUTO-GENERATED by pipeline/build_site_data.py — do not edit by hand.\n")
        f.write("window.WHALE_DATA = ")
        f.write(payload)
        f.write(";\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build site/data/data.js from raw snapshots")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--print-summaries", action="store_true")
    args = ap.parse_args()
    data = build(verbose=not args.quiet)
    write_js(data)
    if not args.quiet:
        print(f"  wrote {OUT_JS}  ({len(data['quarters'])} quarters)")
        if args.print_summaries:
            for q in data["quarters"]:
                print(f"\n[{q['period']}]")
                for lg in LANGS:
                    print(f"  {lg}: {q['summary'][lg]}")


if __name__ == "__main__":
    main()
