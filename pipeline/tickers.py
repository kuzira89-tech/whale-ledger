"""CUSIP → 티커 변환 (OpenFIGI).

13F에는 CUSIP만 있고 티커가 없다. 스냅샷에 나온 CUSIP 가운데 아직 모르는 것을
OpenFIGI 매핑 API에 물어 pipeline/figi_cache.json에 쌓는다. 한 번 찾은 것은 다시
묻지 않으므로 첫 실행만 오래 걸린다. 평가액이 큰 종목부터 묻는다.

  python pipeline/tickers.py                  # 모르는 CUSIP 조회
  python pipeline/tickers.py --max-requests 50

API는 무료이고 키 없이 쓸 수 있다. 키가 없으면 분당 25번, 한 번에 10건이다.
환경변수 OPENFIGI_API_KEY를 주면 한 번에 100건씩 더 빨리 돈다.
손으로 관리하는 ticker_map.json이 항상 우선한다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "figi_cache.json")
MANUAL = os.path.join(HERE, "ticker_map.json")
API = "https://api.openfigi.com/v3/mapping"
US_VENUES = ("US", "UN", "UW", "UQ", "UA", "UR", "UP", "UV")


def _json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_cusip(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{9}", s or "")) and any(c.isdigit() for c in s)


def wanted_cusips() -> list[str]:
    """스냅샷에 나오는 CUSIP을 평가액 합계가 큰 순서로."""
    value: dict[str, int] = {}
    for path in glob.glob(os.path.join(ROOT, "data", "raw", "*", "*", "holdings.json")):
        for row in _json(path, {}).get("holdings", []):
            cusip = row[5] if len(row) > 5 else row[0].split(" (")[0]
            if is_cusip(cusip):
                value[cusip] = value.get(cusip, 0) + int(row[4])
    return sorted(value, key=lambda c: -value[c])


def clean_ticker(t: str) -> str:
    """OpenFIGI는 주식 종류를 'BRK/B'처럼 적는다. 사이트에서는 'BRK.B'로 쓴다.

    미국 티커 모양(글자 1~5개, 종류 접미사 선택)이 아니면 버린다. 상장폐지된 종목은
    '2655787D' 같은 자리표시나 'SIRIEUR' 같은 해외 시세 코드가 돌아오기 때문이다.
    """
    t = (t or "").strip().upper().replace("/", ".")
    return t if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z]{1,2})?", t) else ""


def pick(result: dict) -> dict | None:
    """매핑 응답 한 건에서 쓸 종목을 고른다. 없으면 None."""
    data = result.get("data") or []
    data = [d for d in data if d.get("exchCode") in US_VENUES and clean_ticker(d.get("ticker", ""))]
    if not data:
        return None
    best = min(data, key=lambda d: (US_VENUES.index(d["exchCode"]),
                                    0 if d.get("marketSector") == "Equity" else 1))
    return {"ticker": clean_ticker(best["ticker"]), "type": best.get("securityType") or ""}


def job(cusip: str, us_only: bool, swap: bool = False) -> dict:
    # 글자로 시작하는 9자리는 미국 밖 발행사에 붙는 CINS다.
    cins = cusip[0].isalpha()
    if swap:
        cins = not cins
    j = {"idType": "ID_CINS" if cins else "ID_CUSIP", "idValue": cusip}
    if us_only:
        j["exchCode"] = "US"
    return j


def post(jobs: list[dict], key: str) -> list[dict]:
    headers = {"Content-Type": "application/json", "User-Agent": "whale-ledger"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    req = urllib.request.Request(API, data=json.dumps(jobs).encode("utf-8"), headers=headers, method="POST")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code == 429 and attempt < 5:      # 한도 초과: 한 분 쉬고 다시
                time.sleep(60)
                continue
            raise
    return []


def run(max_requests: int) -> None:
    key = os.environ.get("OPENFIGI_API_KEY", "").strip()
    batch, pause = (100, 0.3) if key else (10, 2.6)
    manual = _json(MANUAL, {}).get("by_cusip", {})
    cache: dict[str, dict] = _json(CACHE, {})
    todo = [c for c in wanted_cusips() if c not in manual and c not in cache]
    print(f"조회할 CUSIP {len(todo)}개 (이미 아는 것 {len(cache)}개, 한 번에 {batch}건)")
    used = 0

    def lookup(cusips: list[str], us_only: bool, swap: bool) -> list[str]:
        """조회해서 cache에 넣고, 못 찾은 CUSIP을 돌려준다."""
        nonlocal used
        missed: list[str] = []
        for i in range(0, len(cusips), batch):
            if used >= max_requests:
                missed.extend(cusips[i:])
                break
            chunk = cusips[i:i + batch]
            try:
                results = post([job(c, us_only, swap) for c in chunk], key)
            except Exception as ex:
                print(f"  ! OpenFIGI 조회 실패 ({ex}). 여기까지 찾은 것만 저장합니다.")
                missed.extend(cusips[i:])
                used = max_requests
                break
            used += 1
            for c, res in zip(chunk, results):
                got = pick(res)
                if got:
                    cache[c] = got
                else:
                    missed.append(c)
            time.sleep(pause)
        return missed

    # 1) 미국 종합 시세 코드로 조회  2) 못 찾은 것은 거래소 조건 없이  3) 식별자 종류를 바꿔서
    missed = lookup(todo, us_only=True, swap=False)
    if missed and used < max_requests:
        missed = lookup(missed, us_only=False, swap=False)
    if missed and used < max_requests:
        missed = lookup(missed, us_only=False, swap=True)
    if used < max_requests:
        for c in missed:                 # 세 번 다 못 찾은 것은 다시 묻지 않는다
            cache[c] = {"ticker": "", "type": ""}

    with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(cache.items())), f, ensure_ascii=False, indent=0, separators=(",", ":"))
        f.write("\n")
    found = sum(1 for v in cache.values() if v.get("ticker"))
    left = sum(1 for c in todo if c not in cache)
    print(f"요청 {used}번. 티커를 찾은 CUSIP {found}개, 못 찾은 것 {len(cache) - found}개, 다음 실행으로 넘긴 것 {left}개")


def main() -> None:
    ap = argparse.ArgumentParser(description="스냅샷의 CUSIP을 OpenFIGI로 티커로 바꾼다")
    ap.add_argument("--max-requests", type=int, default=700, help="한 번 실행에서 API를 부르는 횟수 상한")
    args = ap.parse_args()
    run(args.max_requests)


if __name__ == "__main__":
    main()
