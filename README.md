# 13F Ledger — 큰손 포트폴리오 변화 추적기

미국 SEC **Form 13F-HR** 공시를 분기별로 수집해서, 기관투자자의 포트폴리오가
**무엇이 새로 들어오고(신규), 전량 매도됐고(청산), 얼마나 늘거나 줄었는지(증액/축소)**를
한눈에 보여주는 정적 웹사이트입니다. 첫 대상은 워런 버핏의 **버크셔 해서웨이(CIK 1067983)**.

- **완전 서버리스 / 무료 호스팅**: 서버 없음. GitHub Actions가 분기마다 EDGAR에서 데이터를 긁어
  정적 `data.js`를 커밋하고, Cloudflare Pages가 자동 배포. 비용은 도메인비뿐.
- **한/일 이중 언어**: UI·자동 요약문 모두 한국어/일본어 토글.
- **동아시아 색 관례**: 상승=빨강, 하락=파랑.

---

## 구조

```
whale-ledger/
├── pipeline/               # 데이터 파이프라인 (Python 표준 라이브러리만)
│   ├── edgar.py            #   data.sec.gov에서 13F 제출·정보테이블 XML 취득
│   ├── parse_13f.py        #   정보테이블 XML 파싱 (cusip 집계, 단위 보정, 수정본 병합)
│   ├── build_site_data.py  #   분기간 diff → 비중 재계산 → ko/ja 요약 → data.js 출력
│   ├── run.py              #   진입점: fetch → parse → 매핑 → 스냅샷 저장 → 빌드
│   └── ticker_map.json     #   CUSIP→티커 매핑(신규 분기 EDGAR 파싱용, best-effort)
├── tools/
│   └── seed_bootstrap.py   # 부트스트랩 3개 분기(2025Q3·Q4·2026Q1) 시드 생성기
├── tests/
│   ├── fixture_infotable.xml
│   └── test_parse.py       # 파서·diff 유닛테스트 (표준 unittest, 11개)
├── data/raw/<period>/      # 분기별 원본 스냅샷 (holdings.json + meta.json)
├── site/
│   ├── index.html          # 단일 파일 프론트엔드 (data/data.js 로드)
│   └── data/data.js        # 자동 생성 (window.WHALE_DATA)
└── .github/workflows/update.yml
```

**데이터 흐름:** `EDGAR → parse_13f → data/raw/<분기>/holdings.json → build_site_data → site/data/data.js → 브라우저`

---

## 로컬 실행

```bash
# 1) 부트스트랩 시드 생성 (실데이터 3개 분기, EDGAR 접속 없이 즉시)
python tools/seed_bootstrap.py

# 2) data.js 빌드 (+ 생성된 한/일 요약 확인)
python pipeline/build_site_data.py --print-summaries

# 3) 로컬 서버로 열기 (file:// 는 fetch 제약이 있으니 서버 권장)
python -m http.server -d site 8000
#   -> http://localhost:8000

# 테스트
python -m unittest discover -s tests -v
```

EDGAR에서 실제로 최신 데이터를 당겨오려면:

```bash
export EDGAR_USER_AGENT="whale-ledger youremail@example.com"   # SEC 필수
python pipeline/run.py --cik 1067983 --quarters 8
```

---

## 부트스트랩 → EDGAR 자동 교체

지금 저장소에 든 3개 분기(2025 Q3·Q4, 2026 Q1)는 valuesider에서 교차검증한 **시드 데이터**입니다.
각 분기 합계는 해당 13F 보고 총액과 **0.000% 오차로 일치**하도록 검증됐습니다(`seed_bootstrap.py` 실행 로그 참고).

`run.py`는 **멱등(idempotent)**합니다: 어떤 분기의 `data/raw/<분기>/holdings.json`이 이미 있으면
그 분기는 **건너뜁니다**. 즉,

- 새 분기가 공시되면 → 그 분기만 EDGAR에서 새로 받아 추가.
- 기존 부트스트랩 분기를 EDGAR 원본으로 **교체**하고 싶으면 → 해당 폴더를 지우고
  `python pipeline/run.py --force` 또는 그 분기 폴더 삭제 후 재실행.

즉 시간이 지나면 자연스럽게 EDGAR 원본으로 채워집니다.

---

## 배포 (Cloudflare Pages, 무료)

1. 이 저장소를 GitHub에 push.
2. **Cloudflare Pages → Create project → Connect to Git** 선택.
3. 빌드 설정:
   - **Build command**: (비움)
   - **Build output directory**: `site`
4. GitHub 저장소 **Settings → Secrets and variables → Actions**에
   `EDGAR_USER_AGENT` 시크릿 추가 (예: `whale-ledger youremail@example.com`).
   SEC가 연락처 포함 User-Agent를 요구하므로 필수입니다.

이후 `.github/workflows/update.yml`이 평일 저녁(UTC 22:17)마다 EDGAR를 폴링하고,
**데이터가 실제로 바뀔 때만** 커밋합니다. Pages는 push마다 자동 재배포합니다.
수동 실행은 Actions 탭의 **Run workflow**로 가능합니다.

### 광고

`site/index.html`의 `AD SLOT` 주석 자리에 AdSense `<ins>` 유닛을 넣으면 됩니다.
금융 콘텐츠(YMYL)이므로, 자동 생성 요약은 "정보 제공·투자 권유 아님" 톤을 유지하도록 규칙 기반으로 작성돼 있습니다.

---

## 13F 밖의 자산 (보조 데이터)

13F에는 일본 주식·현금·채권이 없습니다. 이를 보완하려고 `data/supplemental.json`에
**수동 관리** 데이터를 두고, 사이트의 "13F 밖의 자산" 섹션에서 별도로 보여줍니다.
이 수치는 **13F 비중·증감 계산에 전혀 섞이지 않습니다.**

- **일본 5대 상사** (미쓰비시 8058, 미쓰이 8031, 마루베니 8002, 스미토모 8053, 이토추 8001):
  지분율·취득원가·시가. 출처는 일본 대량보유보고서(EDINET)와 버핏 연례서한. 분기별 시가가
  공시되지 않으므로 최신 공시 기준으로 "기준일"을 명시해 표시합니다(분기 셀렉터와 무관).
- **현금·미국채(T-bills)·장기채권(fixed maturity)**: 버크셔 10-Q 연결재무상태표에서 분기별로
  집계하며, 분기 셀렉터와 연동됩니다. "현금+미국채"가 13F 주식 포트폴리오의 몇 배인지도 함께 표시.

**갱신 방법**: 새 10-Q나 연례서한/일본 공시가 나오면 `data/supplemental.json`을 직접 수정하세요.
이 파일은 13F 파이프라인(EDGAR 자동수집)과 무관하므로 자동 갱신되지 않습니다. 파일이 없으면
사이트는 이 섹션을 그냥 생략합니다. 로드맵: 10-Q XBRL 파싱 + EDINET 스크래핑으로 자동화.

## 데이터의 한계 (반드시 인지)

- **13F는 미국 상장 롱 포지션만** 포함합니다. 공매도, 해외 상장 주식(예: 일본 상사),
  현금·채권·비상장 지분은 **빠집니다**. 버크셔의 전체 자산 배분과 다릅니다.
  (일본 주식·현금·채권은 위 "13F 밖의 자산" 섹션에서 10-Q·일본 공시 기반으로 별도 표시.)
- **최대 45일 시차**: 분기말 기준 최대 45일 뒤 공시되므로 실시간이 아닙니다.
- **Confidential treatment / 수정 공시**: 일부 포지션은 비공개 승인 후 나중에
  13F-HR/A로 소급 반영될 수 있습니다. 파서는 수정본 병합을 지원합니다(기본 RESTATEMENT).
- **Liberty Media/Braves 계열 CUSIP 변경**: 2025년 Liberty Live 분사 등으로 일부 종목의
  CUSIP이 바뀌었습니다. diff는 **CUSIP이 아니라 티커 키**로 계산하므로 연속성이 유지됩니다.
  `ticker_map.json`에서는 이 계열을 의도적으로 제외했습니다(신규 분기 파싱 시 원 CUSIP 표시로 노출됨 → 매핑 필요 신호).

---

## 로드맵

- **`ticker_map.json` 자동 보강**: 지금은 확신하는 대형주 CUSIP만 수기 매핑. OpenFIGI API로
  CUSIP→티커를 자동 확장(누락 시 원 CUSIP 폴백)하면 신규 분기도 완전 자동화됩니다.
- **큰손 확장**: 연기금 통합 — GPIF(일본) → NPS(한국) → GPFG(노르웨이). 13F(분기)와
  연기금 연간 공시의 리듬 차이를 UI에서 구분해 표기.
- **종목별 페이지**: 특정 종목을 어느 큰손이 사고파는지 역방향 뷰.
- **알림**: 신규 공시 시 RSS/웹훅.

---

## 면책

본 프로젝트는 SEC EDGAR 공개 데이터를 가공한 **정보 제공용**입니다. 투자 권유나 자문이 아니며,
투자 판단과 그 결과의 책임은 이용자 본인에게 있습니다.
