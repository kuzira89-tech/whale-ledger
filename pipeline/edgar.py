"""EDGAR 13F fetch layer — talks directly to data.sec.gov / www.sec.gov.

Only the Python standard library is used so the GitHub Actions runner needs
no pip install step. The SEC requires a descriptive User-Agent with contact
info; set EDGAR_USER_AGENT (e.g. "whale-ledger admin@example.com").
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Iterator

SEC_DATA = "https://data.sec.gov"
SEC_WWW = "https://www.sec.gov"
RATE_LIMIT_SECONDS = 0.15  # SEC fair-access: stay well under 10 req/s
DEFAULT_UA = "whale-ledger/0.1 (contact: set-EDGAR_USER_AGENT@example.com)"


def _ua() -> str:
    ua = os.environ.get("EDGAR_USER_AGENT", "").strip()
    return ua or DEFAULT_UA


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": _ua(),
        "Accept-Encoding": "gzip, deflate",
        "Host": url.split("/")[2],
    })
    time.sleep(RATE_LIMIT_SECONDS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    return raw


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8"))


@dataclass
class Filing:
    accession: str          # dashed, e.g. 0001193125-26-226661
    form: str               # 13F-HR or 13F-HR/A
    filing_date: str        # yyyy-mm-dd (date filed)
    report_date: str        # yyyy-mm-dd (period of report)
    primary_doc: str = ""   # e.g. primary_doc.xml
    info_table_url: str = ""  # resolved URL to the information table XML

    @property
    def acc_nodash(self) -> str:
        return self.accession.replace("-", "")


def _submissions_url(cik: int) -> str:
    return f"{SEC_DATA}/submissions/CIK{cik:010d}.json"


def list_13f_filings_with_name(cik: int) -> tuple[str, list[Filing]]:
    """Return all 13F-HR / 13F-HR/A filings from the recent submissions feed,
    newest first. (For a filer as active as Berkshire the recent feed is
    sufficient; older overflow files are ignored on purpose.)"""
    data = _get_json(_submissions_url(cik))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accns = recent.get("accessionNumber", [])
    fdates = recent.get("filingDate", [])
    rdates = recent.get("reportDate", [])
    docs = recent.get("primaryDocument", [])
    out: list[Filing] = []
    for i, form in enumerate(forms):
        if not form.startswith("13F-HR"):
            continue
        out.append(Filing(
            accession=accns[i],
            form=form,
            filing_date=fdates[i],
            report_date=rdates[i],
            primary_doc=docs[i] if i < len(docs) else "",
        ))
    out.sort(key=lambda f: (f.report_date, f.filing_date), reverse=True)
    return data.get("name", ""), out


def list_13f_filings(cik: int) -> list[Filing]:
    return list_13f_filings_with_name(cik)[1]


def _filing_index_url(cik: int, acc_nodash: str) -> str:
    return f"{SEC_WWW}/cgi-bin/browse-edgar"  # not used; kept for reference


def resolve_info_table_url(cik: int, filing: Filing) -> str:
    """Find the information-table XML inside a filing folder.

    The folder JSON index lists every document; we pick the XML that is NOT
    the primary_doc (the primary doc is the cover/summary, the other XML is
    the holdings information table)."""
    folder = f"{SEC_WWW}/Archives/edgar/data/{cik}/{filing.acc_nodash}"
    idx = _get_json(f"{folder}/index.json")
    items = idx.get("directory", {}).get("item", [])
    chosen = pick_info_table(items, filing.primary_doc)
    return f"{folder}/{chosen}" if chosen else ""


def pick_info_table(items: list[dict], primary_doc: str = "") -> str:
    """Pick the information-table XML out of a filing folder listing.

    The cover page is always primary_doc.xml (the submissions feed reports it
    with an XSL prefix such as "xslForm13F_X02/primary_doc.xml", so compare by
    basename). Among the remaining XML files prefer one whose name says it is
    the table; otherwise take the largest, since filers name the table freely.
    """
    primary = os.path.basename(primary_doc or "").lower()
    cands = [it for it in items
             if it.get("name", "").lower().endswith(".xml")
             and it["name"].lower() not in (primary, "primary_doc.xml")]
    if not cands:
        return ""

    def size(it: dict) -> int:
        try:
            return int(it.get("size") or 0)
        except (TypeError, ValueError):
            return 0

    named = [it for it in cands
             if any(k in it["name"].lower() for k in ("infotable", "info_table", "informationtable", "table"))]
    return max(named or cands, key=size)["name"]


def parse_amendment_type(cover_xml: str) -> str:
    """Read <amendmentType> (RESTATEMENT / NEW HOLDINGS) from a 13F cover page."""
    m = re.search(r"<(?:\w+:)?amendmentType>\s*([^<]+?)\s*</", cover_xml)
    return m.group(1).upper() if m else ""


def fetch_amendment_type(cik: int, filing: Filing) -> str:
    """Amendment type of a 13F-HR/A, or "" when the cover page cannot be read."""
    url = f"{SEC_WWW}/Archives/edgar/data/{cik}/{filing.acc_nodash}/primary_doc.xml"
    try:
        return parse_amendment_type(_get(url).decode("utf-8", errors="replace"))
    except Exception:
        return ""


def fetch_info_table_xml(cik: int, filing: Filing) -> str:
    url = filing.info_table_url or resolve_info_table_url(cik, filing)
    filing.info_table_url = url
    if not url:
        raise RuntimeError(f"no information table xml found for {filing.accession}")
    return _get(url).decode("utf-8", errors="replace")


def group_by_period(filings: list[Filing]) -> dict[str, list[Filing]]:
    """Group filings by report_date so that a 13F-HR/A can be merged with its
    original 13F-HR for the same period."""
    by: dict[str, list[Filing]] = {}
    for f in filings:
        by.setdefault(f.report_date, []).append(f)
    # within a period, original first then amendments by filing date
    for period in by:
        by[period].sort(key=lambda f: (f.form.endswith("/A"), f.filing_date))
    return by
