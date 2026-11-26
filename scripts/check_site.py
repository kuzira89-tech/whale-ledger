#!/usr/bin/env python3
"""만들어진 site/를 검사한다. 문제가 있으면 내용을 적고 1로 끝난다.

- 사이트 안 링크(href, og:image)가 모두 실제 파일로 이어지는가
- 페이지마다 제목, 설명, 대표 주소, 다른 언어 판, 공유 미리보기가 있는가
- 한국어판과 일본어판의 페이지가 짝이 맞는가
- sitemap.xml이 만들어진 페이지와 같은가
- 브라우저 스크립트가 섞여 들어가지 않았는가(이 사이트는 스크립트를 쓰지 않는다)
- 채우지 못한 자리표시({name} 같은 것)가 화면에 남지 않았는가
- site/가 지금의 소스·데이터로 만든 것인가(site/build.txt의 지문)

  python scripts/check_site.py
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
sys.path.insert(0, os.path.join(ROOT, "sitegen"))
SITE_URL = "https://whaleportfolio.com"
HAND_WRITTEN = {"privacy.html"}          # 손으로 관리하는 파일. 생성기의 규칙을 따르지 않는다.
REDIRECTED = ("/dashboard", "/portfolio", "/consensus", "/advertising")


def url_of(path: str) -> str:
    rel = os.path.relpath(path, SITE).replace(os.sep, "/")
    return "/" + rel[:-len("index.html")] if rel.endswith("index.html") else "/" + rel


def exists(url: str) -> bool:
    url = url.split("#")[0].split("?")[0]
    if url == "/privacy":
        return os.path.exists(os.path.join(SITE, "privacy.html"))
    target = os.path.join(SITE, url.lstrip("/"))
    if url.endswith("/"):
        return os.path.exists(os.path.join(target, "index.html"))
    return os.path.exists(target)


def main() -> int:
    pages = []
    for d, _, files in os.walk(SITE):
        for f in files:
            if f.endswith(".html") and f not in HAND_WRITTEN:
                pages.append(os.path.join(d, f))
    errors: list[str] = []
    urls = set()
    for path in sorted(pages):
        url = url_of(path)
        urls.add(url)
        with open(path, encoding="utf-8") as fh:
            html = fh.read()

        def bad(msg: str) -> None:
            errors.append(f"{url}: {msg}")

        for href in set(re.findall(r'href="(/[^"]*)"', html)):
            if not exists(href):
                bad(f"끊어진 링크 {href}")
        for need, pat in (("제목", r"<title>[^<]+</title>"),
                          ("설명", r'<meta name="description" content="[^"]+">'),
                          ("대표 주소", rf'<link rel="canonical" href="{re.escape(SITE_URL + url)}">'),
                          ("og:title", r'<meta property="og:title" content="[^"]+">'),
                          ("twitter:card", r'<meta name="twitter:card" content="summary_large_image">')):
            if not re.search(pat, html):
                bad(f"{need} 없음")
        og = re.search(r'<meta property="og:image" content="([^"]+)">', html)
        if not og or not og.group(1).startswith(SITE_URL) or not exists(og.group(1)[len(SITE_URL):]):
            bad(f"공유 미리보기 그림이 없거나 끊어짐: {og.group(1) if og else None}")
        alts = dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', html))
        for lg in ("ko", "ja", "x-default"):
            if lg not in alts:
                bad(f"hreflang {lg} 없음")
            elif not exists(alts[lg][len(SITE_URL):]):
                bad(f"hreflang {lg}가 없는 페이지를 가리킴: {alts[lg]}")
        if re.search(r"<script\b", html, re.I):
            bad("브라우저 스크립트가 들어 있음")
        text = re.sub(r"<[^>]+>", " ", html)
        left = re.search(r"\{[a-z_]+\}", text)
        if left:
            bad(f"채우지 못한 자리표시 {left.group(0)}")
        if re.search(r"\b(None|nan|undefined)\b", text):
            bad("화면에 None/nan이 찍힘")

    ko = {u for u in urls if not u.startswith("/ja/")}
    ja = {u[3:] for u in urls if u.startswith("/ja/")}
    for u in sorted(ko - ja)[:10]:
        errors.append(f"{u}: 일본어판이 없음")
    for u in sorted(ja - ko)[:10]:
        errors.append(f"/ja{u}: 한국어판이 없음")

    with open(os.path.join(SITE, "sitemap.xml"), encoding="utf-8") as fh:
        listed = {u[len(SITE_URL):] for u in re.findall(r"<loc>([^<]+)</loc>", fh.read())}
    for u in sorted(urls - listed)[:10]:
        errors.append(f"{u}: sitemap.xml에 없음")
    for u in sorted(listed - urls)[:10]:
        errors.append(f"{u}: sitemap.xml에만 있고 페이지가 없음")

    with open(os.path.join(SITE, "_redirects"), encoding="utf-8") as fh:
        redirects = fh.read()
    for old in REDIRECTED:
        if f"{old} / 301" not in redirects:
            errors.append(f"_redirects: 예전 주소 {old}의 넘김이 빠짐")

    import build
    stamp = os.path.join(SITE, "build.txt")
    built = open(stamp, encoding="utf-8").read().split()[-1] if os.path.exists(stamp) else ""
    if built != build.inputs_digest():
        errors.append("site/가 지금의 소스·데이터와 맞지 않습니다. python3 sitegen/build.py로 다시 만드세요.")

    if errors:
        print(f"site check FAILED: {len(errors)} problem(s)", file=sys.stderr)
        for line in errors[:40]:
            print("  " + line, file=sys.stderr)
        if len(errors) > 40:
            print(f"  ... 외 {len(errors) - 40}건", file=sys.stderr)
        return 1
    print(f"site check ok: {len(pages)} pages, {len(urls)} urls, ko/ja paired, links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
