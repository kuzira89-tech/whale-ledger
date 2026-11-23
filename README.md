# 큰손 포트폴리오

미국 SEC **Form 13F-HR** 공시를 분기마다 수집해서, 큰손들이 무엇을 들고 있고
이번 분기에 무엇을 사고팔았는지 큰손별로 보여주는 정적 웹사이트입니다.

- **서버 없음**: GitHub Actions가 EDGAR에서 공시를 받아 데이터와 HTML을 커밋하고,
  Cloudflare Pages가 `site/` 폴더를 그대로 배포합니다.
- **가벼움**: 페이지는 완성된 HTML과 CSS 한 장입니다. 브라우저에서 도는 스크립트가 없고,
  트리맵과 막대는 빌드할 때 계산한 CSS 상자입니다.
- **색 관례**: 늘림은 주황, 줄임은 파랑입니다.

## 구조

```
managers.json            추적 대상 (slug, CIK, 이름). 여기에 한 줄 추가하면 큰손이 늘어납니다.
pipeline/
  collect.py             진입점: managers.json 전체를 돌며 EDGAR에서 13F를 받는다
  edgar.py               data.sec.gov / www.sec.gov 조회
  parse_13f.py           보유 내역 XML 파싱, 정정 공시 병합
  ticker_map.json        CUSIP → 티커 (손으로 관리)
sitegen/
  build.py               data/raw → site/ 정적 HTML
  names_ko.json          티커 → 한국어 종목명
data/raw/<slug>/<분기>/  분기별 스냅샷 (holdings.json + meta.json)
site/                    배포되는 폴더 (build.py가 생성, privacy.html만 손으로 관리)
tests/                   unittest
```

주소는 `/`(큰손 목록), `/whales/<slug>/`(최신 분기), `/whales/<slug>/2026q2/`(지난 분기)입니다.

## 로컬 실행

```bash
python sitegen/build.py                      # site/ 생성
python -m http.server -d site 8000           # http://localhost:8000
python -m unittest discover -s tests -v      # 테스트

export EDGAR_USER_AGENT="whale-ledger youremail@example.com"   # SEC 필수
python pipeline/collect.py                   # 전체 수집
python pipeline/collect.py --only berkshire  # 한 곳만
```

표준 라이브러리만 씁니다. 설치할 패키지가 없습니다.

## 수집 규칙

- 이미 받은 분기는 그 분기의 공시 목록(원본 + 정정)이 그대로면 건너뜁니다.
  정정 공시(13F-HR/A)가 새로 올라오면 그 분기만 다시 받습니다.
- 정정 공시는 표지의 종류를 읽어 처리합니다. `RESTATEMENT`는 통째로 바꾸고,
  `NEW HOLDINGS`는 원본에 더합니다.
- CIK마다 SEC 등록명에 `expect` 문자열이 들어 있는지 확인합니다. 다르면 그 큰손은 건너뜁니다.
- `ticker_map.json`에 없는 CUSIP은 발행사 이름과 CUSIP으로 표시됩니다.

## 배포

Cloudflare Pages를 이 저장소에 연결하고, Build command는 비우고 Build output directory를
`site`로 둡니다. GitHub 저장소 시크릿 `EDGAR_USER_AGENT`가 필요합니다.
`.github/workflows/update.yml`이 평일마다 수집과 빌드를 돌리고, 바뀐 것이 있을 때만 커밋합니다.

## 데이터의 한계

- 13F에는 분기 말 미국 상장 주식 보유분만 들어갑니다. 공매도, 현금, 채권, 대부분의 해외 주식은 빠집니다.
- 공시는 분기가 끝나고 최대 45일 뒤에 나옵니다.
- 매수·매도 금액은 추정치입니다. 주식 수 변화에 분기 말 가격을 곱했습니다. 13F에는 거래 가격과 날짜가 없습니다.
- `data/supplemental.json`(일본 상사 지분, 현금·채권)은 예전 화면에서 쓰던 수동 데이터입니다.
  새 화면에는 아직 넣지 않았습니다.

## 면책

SEC EDGAR 공개 데이터를 가공한 정보 제공용 사이트입니다. 투자 권유나 자문이 아닙니다.
