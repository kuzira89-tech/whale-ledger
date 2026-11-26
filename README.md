# 큰손 포트폴리오

미국 SEC **Form 13F-HR** 공시를 분기마다 수집해서, 큰손들이 무엇을 들고 있고
이번 분기에 무엇을 사고팔았는지 큰손별, 종목별, 분기별로 보여주는 정적 웹사이트입니다.

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
  tickers.py             새로 나온 CUSIP을 OpenFIGI로 조회 → figi_cache.json
  ticker_map.json        CUSIP → 티커 (손으로 관리, 항상 우선). 식별 번호가 바뀐 종목도 여기서 잇는다
  splits.json            손으로 확인한 주식 분할·병합
sitegen/
  build.py               data/raw → site/ 정적 HTML
  market.py              큰손을 가로지르는 계산: 분할 추정, 종목별 보유 현황, 분기 요약
  ogimage.py             공유 미리보기 그림(PNG)
  names_ko.json          티커 → 한국어 종목명
  names_ja.json          티커 → 일본어 종목명
data/raw/<slug>/<분기>/  분기별 스냅샷 (holdings.json + meta.json)
site/                    배포되는 폴더 (build.py가 생성, privacy.html만 손으로 관리)
scripts/
  check.sh               전체 검사: 테스트 → 사이트 생성 → 사이트 검사
  check_site.py          만들어진 site/ 검사 (끊어진 링크, 빠진 태그, 언어 짝, 소스와 어긋남)
  hooks/                 Claude Code hooks (편집 뒤, 턴을 끝내기 전)
tests/                   unittest
CLAUDE.md                Claude Code가 이 리포에서 알아야 할 것
```

| 주소 | 내용 |
|---|---|
| `/` | 큰손 목록과 이번 분기 요약 |
| `/whales/<slug>/` | 큰손 한 곳의 최신 분기. 지난 분기는 `/whales/<slug>/2026q2/` |
| `/stocks/<ticker>/` | 종목 하나를 누가 들고 있고 분기마다 어떻게 했는지. 목록은 `/stocks/` |
| `/quarters/2026q3/` | 한 분기에 큰손들이 함께 사고판 종목 |
| `/guide/` | 13F 읽는 법과 이 사이트의 계산 방식 |

일본어판은 같은 구조로 `/ja/` 아래에 만듭니다. 화면 문구는 `sitegen/build.py`의 `T`,
큰손 이름은 `managers.json`의 `ja`·`person_ja`·`place_ja`, 종목명은 `sitegen/names_ko.json`과
`sitegen/names_ja.json`(티커 → 이름)에 있습니다. 사전에 없는 종목은 13F의 영문 발행사명으로 나옵니다.

## 로컬 실행

```bash
bash scripts/check.sh                        # 테스트 → site/ 생성 → 사이트 검사
python sitegen/build.py                      # site/ 생성만
python -m http.server -d site 8000           # http://localhost:8000
python -m unittest discover -s tests -v      # 테스트만

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
- `ticker_map.json`에도 OpenFIGI에도 없는 CUSIP은 발행사 이름과 CUSIP으로 표시됩니다.

## 주식 분할과 종목 코드 변경

13F에는 분할 정보가 없어서, 분할이 있던 분기에는 보유자 전원이 산 것처럼 보입니다.

- `pipeline/splits.json`에 적힌 분할만 계산에 반영합니다. 직전 분기 주식 수에 비율을 곱해 비교합니다.
- 생성기가 가격과 주식 수의 모양으로 분할을 추정하지만, 비율을 자주 틀려서 계산에는 쓰지 않습니다.
  추정된 종목은 빌드 로그에 `unconfirmed split suspects`로 나오고, 분기 요약의 순위에서만 빠집니다.
  회사 공시로 확인한 뒤 `splits.json`에 옮기세요. 주가 급락이었다면 `not_splits`에 적습니다.
- 회사 재편으로 CUSIP이 바뀌면 "옛 종목 청산 + 새 종목 신규"로 보입니다. 두 곳 이상에서 그런 짝이 보이면
  빌드 로그에 `identifier change suspects`로 나옵니다. 같은 종목이면 `ticker_map.json`에서 옛 CUSIP을
  새 티커로 잇습니다.

## 배포

Cloudflare Pages를 이 저장소에 연결하고, Build command는 비우고 Build output directory를
`site`로 둡니다. GitHub 저장소 시크릿 `EDGAR_USER_AGENT`가 필요합니다.
`.github/workflows/update.yml`이 평일마다 수집과 빌드를 돌리고, 테스트와 사이트 검사를 통과하고
바뀐 것이 있을 때만 커밋합니다. `.github/workflows/ci.yml`은 PR과 `rebuild` 브랜치에서 같은 검사를 돌립니다.

www → 루트 넘김과 브라우저 언어에 따른 `/ja/` 넘김은 Cloudflare 대시보드의 리디렉션 규칙입니다.

## 데이터의 한계

- 13F에는 분기 말 미국 상장 주식 보유분만 들어갑니다. 공매도, 현금, 채권, 대부분의 해외 주식은 빠집니다.
- 공시는 분기가 끝나고 최대 45일 뒤에 나옵니다.
- 매수·매도 금액은 추정치입니다. 주식 수 변화에 분기 말 가격을 곱했습니다. 13F에는 거래 가격과 날짜가 없습니다.
- 분사로 받은 주식은 신규 매수처럼 보입니다. 확인하지 못한 분할과 종목 코드 변경도 매매처럼 보입니다.
- 종목 페이지는 세 곳 이상이 들고 있거나 어느 한 곳의 상위 25위 안에 드는 종목에만 만듭니다.
- 분기 요약은 주식 수를 5% 이상 바꾼 경우만 샀다·팔았다로 셉니다.
- `data/supplemental.json`(일본 상사 지분, 현금·채권)은 예전 화면에서 쓰던 수동 데이터입니다.
  새 화면에는 아직 넣지 않았습니다.

## 면책

SEC EDGAR 공개 데이터를 가공한 정보 제공용 사이트입니다. 투자 권유나 자문이 아닙니다.
