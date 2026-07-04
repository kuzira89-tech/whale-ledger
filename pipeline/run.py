"""End-to-end pipeline entry point.

  python pipeline/run.py --cik 1067983 --quarters 8

For each of the newest N reporting periods:
  * if data/raw/<period>/holdings.json already exists -> skip fetch
    (idempotent; also means the hand-seeded bootstrap is never overwritten
     unless you delete it first)
  * otherwise fetch the 13F information table from EDGAR, parse it, map each
    CUSIP to a ticker via ticker_map.json, and write the compact snapshot.

Then rebuild site/data/data.js from every snapshot on disk.
"""
from __future__ import annotations

import argparse
import json
import os

from build_site_data import build, write_js, OUT_JS
import edgar
import parse_13f

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")
TICKER_MAP = os.path.join(HERE, "ticker_map.json")


def _load_ticker_map() -> dict:
    if not os.path.exists(TICKER_MAP):
        return {"by_cusip": {}}
    with open(TICKER_MAP, encoding="utf-8") as f:
        return json.load(f)


def _map_row(h: parse_13f.RawHolding, tmap: dict) -> list:
    entry = tmap.get("by_cusip", {}).get(h.cusip.upper(), {})
    ticker = entry.get("ticker") or h.cusip.upper()
    name = entry.get("name") or h.name
    cl = entry.get("cl", "")
    if h.put_call:  # keep options visibly distinct so the diff key stays unique
        ticker = f"{ticker} ({h.put_call})"
    return [ticker, name, cl, h.shares, h.value]


def _write_snapshot(period: str, rows: list, meta: dict) -> None:
    pdir = os.path.join(RAW_DIR, period)
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "holdings.json"), "w", encoding="utf-8") as f:
        json.dump({"period": period, "holdings": rows}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(pdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def fetch_period(cik: int, filings: list[edgar.Filing], tmap: dict, verbose: bool) -> None:
    period = filings[0].report_date
    # base = original 13F-HR (first after sort), then merge any amendments
    base_filing = filings[0]
    xml = edgar.fetch_info_table_xml(cik, base_filing)
    holdings = parse_13f.parse_info_table(xml, period)
    used = base_filing
    for amd in filings[1:]:
        if not amd.form.endswith("/A"):
            continue
        axml = edgar.fetch_info_table_xml(cik, amd)
        aholdings = parse_13f.parse_info_table(axml, period)
        # Without the cover page we cannot read the amendment type reliably;
        # default to RESTATEMENT (full replace) which is the common case.
        holdings = parse_13f.merge_amendment(holdings, aholdings, "RESTATEMENT")
        used = amd
    rows = [_map_row(h, tmap) for h in holdings]
    rows.sort(key=lambda r: r[4], reverse=True)
    meta = {
        "period": period,
        "filed": used.filing_date,
        "form": used.form,
        "accession": used.accession,
        "total_value": parse_13f.total_value(holdings),
        "num_holdings": len(holdings),
        "source": "EDGAR 13F information table (data.sec.gov)",
    }
    _write_snapshot(period, rows, meta)
    if verbose:
        print(f"  fetched {period}: {len(rows)} holdings  [{used.form} {used.accession}]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch 13F snapshots and build data.js")
    ap.add_argument("--cik", type=int, default=1067983)
    ap.add_argument("--quarters", type=int, default=8, help="how many recent periods to ensure")
    ap.add_argument("--force", action="store_true", help="re-fetch even if snapshot exists")
    ap.add_argument("--no-build", action="store_true", help="skip data.js rebuild")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    verbose = not args.quiet

    tmap = _load_ticker_map()
    try:
        filings = edgar.list_13f_filings(args.cik)
    except Exception as e:  # offline / rate-limited: fall back to whatever is on disk
        print(f"  ! could not reach EDGAR ({e}); building from existing snapshots only")
        filings = []

    if filings:
        by_period = edgar.group_by_period(filings)
        periods_sorted = sorted(by_period.keys(), reverse=True)[:args.quarters]
        for period in periods_sorted:
            snap = os.path.join(RAW_DIR, period, "holdings.json")
            if os.path.exists(snap) and not args.force:
                if verbose:
                    print(f"  skip {period}: snapshot present")
                continue
            try:
                fetch_period(args.cik, by_period[period], tmap, verbose)
            except Exception as e:
                print(f"  ! {period}: fetch failed ({e}); leaving existing data untouched")

    if not args.no_build:
        data = build(verbose=verbose)
        write_js(data)
        if verbose:
            print(f"  built {OUT_JS}  ({len(data['quarters'])} quarters)")


if __name__ == "__main__":
    main()
