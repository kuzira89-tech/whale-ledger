"""Parse a 13F information-table XML into normalized holding rows.

13F XML uses a namespace and one <infoTable> element per lot; a single issuer
can appear on several rows (different lots, or a share + option line). We
aggregate by (cusip, put_call) so each key is one economic position.

Value units: since 2023-Q3 (filings on/after 2023-09) the <value> element is
reported in whole US dollars. Before that it was in thousands. `value_multiplier`
handles the boundary so historical backfill stays consistent.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


def _strip_ns(xml_text: str) -> str:
    # Remove xmlns declarations and any element/attribute namespace prefixes so
    # ElementTree tag names are bare ("infoTable", "nameOfIssuer", ...).
    xml_text = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", xml_text)
    xml_text = re.sub(r"<(/?)(\w+):", r"<\1", xml_text)
    return xml_text


def _text(el, tag: str, default: str = "") -> str:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else default


@dataclass
class RawHolding:
    cusip: str
    name: str
    title_of_class: str
    value: int              # US dollars (after multiplier)
    shares: int
    share_type: str         # SH / PRN
    put_call: str           # "", PUT, or CALL
    discretion: str = ""

    @property
    def key(self) -> str:
        base = self.cusip.upper()
        return f"{base}:{self.put_call}" if self.put_call else base


def value_multiplier_for_period(report_date: str) -> int:
    """Return 1 if <value> is already in dollars, else 1000 (pre-2023Q3)."""
    try:
        y, m, _ = report_date.split("-")
        y, m = int(y), int(m)
    except Exception:
        return 1
    return 1 if (y > 2023 or (y == 2023 and m >= 9)) else 1000


def parse_info_table(xml_text: str, report_date: str) -> list[RawHolding]:
    root = ET.fromstring(_strip_ns(xml_text))
    mult = value_multiplier_for_period(report_date)
    agg: dict[str, RawHolding] = {}
    for it in root.iter("infoTable"):
        cusip = _text(it, "cusip")
        if not cusip:
            continue
        name = _text(it, "nameOfIssuer")
        toc = _text(it, "titleOfClass")
        raw_value = _text(it, "value", "0").replace(",", "")
        try:
            value = int(round(float(raw_value))) * mult
        except ValueError:
            value = 0
        shrs_el = it.find("shrsOrPrnAmt")
        if shrs_el is not None:
            amount = _text(shrs_el, "sshPrnamt", "0").replace(",", "")
            stype = _text(shrs_el, "sshPrnamtType", "SH")
        else:
            amount, stype = "0", "SH"
        try:
            shares = int(round(float(amount)))
        except ValueError:
            shares = 0
        put_call = _text(it, "putCall").upper()
        disc = _text(it, "investmentDiscretion")
        h = RawHolding(cusip=cusip, name=name, title_of_class=toc, value=value,
                       shares=shares, share_type=stype, put_call=put_call,
                       discretion=disc)
        if h.key in agg:
            cur = agg[h.key]
            cur.value += h.value
            cur.shares += h.shares
        else:
            agg[h.key] = h
    return list(agg.values())


def merge_amendment(base: list[RawHolding], amend: list[RawHolding],
                    amendment_type: str) -> list[RawHolding]:
    """Merge a 13F-HR/A into the base holdings.

    amendment_type == "RESTATEMENT": the amendment fully replaces the base.
    amendment_type == "NEW HOLDINGS": union — amendment rows are added on top.
    Anything else: treat as restatement (safest default)."""
    at = (amendment_type or "").upper()
    if at == "NEW HOLDINGS":
        by = {h.key: h for h in base}
        for h in amend:
            by[h.key] = h
        return list(by.values())
    return amend if amend else base


def total_value(holdings: list[RawHolding]) -> int:
    return sum(h.value for h in holdings)
