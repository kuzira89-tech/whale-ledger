# 큰손 포트폴리오 (whaleportfolio.com)

## 검사
- 전체: `bash scripts/check.sh` (테스트 → 사이트 생성 → 사이트 검사)
- 테스트만: `python3 -m unittest discover -s tests`
- 테스트 파일 하나: `python3 -m unittest tests.test_market -v`
- 화면: `python3 -m http.server -d site 8000` 뒤 헤드리스 크롬으로 캡처해서 직접 본다. 테스트는 배치가 깨진 것을 잡지 못한다.

## 배포
- `main`이 운영이다. main에 푸시하면 Cloudflare가 `site/`를 그대로 내보낸다(빌드 명령 없음). 그래서 생성된 `site/`도 커밋한다.
- 작업은 `rebuild` 브랜치에서 하고 PR로 main에 넣는다. main 반영은 사용자가 승인한다.
- 평일 22:17 UTC에 Actions "Update 13F data"가 main에서 수집·생성·커밋한다. PR이 열려 있는 동안 main에 데이터 커밋이 생기면 `site/`가 충돌한다. main을 합치고 `python3 sitegen/build.py`로 다시 만든다.
- www → 루트, 브라우저 언어별 `/ja/` 넘김은 Cloudflare 대시보드의 규칙이다. 리포에 없다.

## 코드만 봐서는 알 수 없는 것
- 클라우드 작업 환경의 셸에서는 sec.gov, openfigi.com, whaleportfolio.com에 닿지 않는다. 수집(`pipeline/collect.py`, `pipeline/tickers.py`)은 GitHub Actions에서만 돈다. 여기서는 `data/raw/`의 스냅샷으로 생성기만 돌린다.
- 표준 라이브러리만 쓴다. 브라우저 스크립트도 쓰지 않는다. 차트와 미리보기 그림은 빌드할 때 계산한다.
- `site/`에서 손으로 관리하는 파일은 `privacy.html`뿐이다. 나머지는 `sitegen/build.py`가 지우고 다시 만든다.
- 화면 문구는 `sitegen/build.py`의 `T`에 한국어와 일본어를 함께 넣는다.
- 주식 분할은 `pipeline/splits.json`에 손으로 확인한 것만 계산에 쓴다. 추정(`market.split_factor`)은 비율을 틀린다. CRWD 4:1을 3:1로, KLAC 10:1을 3:1로 읽었다. 빌드 로그의 `unconfirmed split suspects`와 `identifier change suspects`는 회사 공시로 확인한 뒤 `splits.json`이나 `ticker_map.json`에 옮긴다.
- 사이트에 올리는 숫자를 바꾸는 작업은, 바뀐 종목 두세 개를 뉴스나 공시와 대조해 본다.
