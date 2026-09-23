# PREP-B 공개 시세·OHLCV 원문 준비 및 분석 보고서

- **작업 식별자**: PREP-B (공개 시세 및 OHLCV 원문 준비 / Public Quotes & OHLCV Source Preparation)
- **수행 주체**: Gemini Implementation Session B (Worktree: `gemini-b`, Branch: `codex/gemini-b`, Baseline: `68fab98`)
- **모델**: `gemini-3.8-flash-high` (Gemini 3.8 Flash High)
- **작업 일시**: 2026-09-23
- **적용 요구사항 및 설계**: REQ-v1 R06–R08, DESIGN-v0.1 (§3, §4, §9)
- **조회 주체 및 안전 경계 명시**:
  - 본 작업 중 에이전트 세션의 직접적인 웹 도구(`read_url`), 외부 작업 폴더 접근, 셸(`run_command`), git, pip, 개인 DB(`personal.db`), 자격 증명(credentials) 접근은 수행하지 않았거나 정책에 의해 차단되었습니다.
  - 본 문서의 원문 데이터 및 관측 사실은 **총괄(Supervisor)이 직접 웹 도구 및 환경에서 수집하여 worktree 내에 제공한 자료**(`docs/workflow/source-checks-2026-09-23.md`, `workspace/runs/source-inputs/naver_basic.json`, `workspace/runs/source-inputs/naver_ohlcv.json`)를 바탕으로 정밀 분석한 결과입니다.
  - 런타임/테스트/계약 코드의 변경은 일체 수행하지 않았습니다.

---

## 1. 시장별 공개 원문 후보 순서, URL 및 현재 상태

설계 명세(DESIGN-v0.1 §3 R06)에 따른 시장별 공급자 후보 체계와 현재 조사 상태입니다.

| 시장 / 형태 | 1순위 (공식/구조화) | 2순위 (웹 원문) | 3순위 (대체 원문) | 현재 검증 상태 |
|---|---|---|---|---|
| **한국 상장 주식·ETF** | KRX 정보데이터시스템 (`data.krx.co.kr`) | 네이버페이 증권 (`stock.naver.com`) | Investing.com 한국 | **부분 검증 완료** (네이버페이 증권 JSON API 응답 총괄 수집본 확인 완료, KRX/Investing 미검증) |
| **미국 상장 주식·ETF** | 거래소 / 승인 타임스탬프 공급자 | Investing.com 원문 (`investing.com/equities/...`) | 승인 대체 시세 페이지 | **부분 검증 완료** (Investing Apple 페이지 총괄 수집 확인, 정규장/시간외 분리 확인, 거래소 API 미검증) |
| **일본 상장 주식·ETF** | JPX 공식 제공 경로 | 현지 웹 원문 (Yahoo Finance JP 등) | Investing.com Japan | **미검증 (Unverified)** (후보 경로만 식별됨, live 접근 미실시) |
| **가상자산 (BTC)** | Kraken 공개 API (`api.kraken.com`) | 타 승인 거래소 (Coinbase 등) | 동일 Pair 웹 원문 | **미검증 (Unverified)** (엔드포인트 규격 식별, live probe 미실시) |
| **귀금속 (금·은)** | 거래소/벤치마크 (LBMA, COMEX 등) | 공인 발행사 웹 원문 | 승인 대체 시세 | **미검증 (Unverified)** (현물/선물/ETF 메타데이터 규격만 식별, live 미실시) |

---

## 2. 총괄 수집 실제 응답 분석 및 파서 요구사항

총괄이 수집하여 배치한 실제 공개 원문 응답 2종과 사전 확인 문서를 분석한 세부 결과입니다.

### A. 한국 주식 기본 시세 (`naver_basic.json` 분석)

- **수집 출처**: 네이버페이 증권 모바일 내부 API (`https://m.stock.naver.com/api/stock/005930/basic` 추정)
- **확인 시각**: `2026-09-23T16:47:56+09:00` (총괄 수집 타임스탬프)
- **실제 관측된 핵심 필드**:
  - 종목 식별: `itemCode="005930"`, `stockName="삼성전자"`, `reutersCode="005930"`
  - 현재 가격: `closePrice="285,000"` (천 단위 쉼표 포함 문자열)
  - 전일비/등락률: `compareToPreviousClosePrice="8,500"`, `fluctuationsRatio="3.07"`, `compareToPreviousPrice={"code":"2","text":"상승","name":"RISING"}`
  - 거래 상태: `marketStatus="OPEN"`, `tradeStopType={"code":"1","text":"운영.Trading"}`
  - 관측 시각: `localTradedAt="2026-09-23T16:47:56+09:00"` (ISO 8601, Asia/Seoul 오프셋 포함)
  - 거래소 정보: `stockExchangeType={"code":"KS", "zoneId":"Asia/Seoul", "delayTime":0, "startTime":"0900", "endTime":"1530", "closePriceSendTime":"1630", "nameKor":"코스피"}`
  - 세션 정보: `marketSessionType="afterMarket"`
  - 시간외 시세 블록: `overMarketPriceInfo={"tradingSessionType":"AFTER_MARKET", "overPrice":"285,000", "localTradedAt":"2026-09-23T16:48:31.5+09:00"}`
- **부족한 메타데이터 및 설계 주의사항 (R06 / C02)**:
  1. **통화(`currency`) 명시 필드 누락**: JSON 어디에도 `"KRW"` 통화 코드가 없음. `stockExchangeType.code == "KS"` 및 `nationCode == "KOR"`로부터 파서 수준에서 통화 `KRW`를 매핑하고 검증해야 함.
  2. **정규장 종가와 시간외 가격 혼합 차단**: 수집 시각(16:47)은 정규장(09:00~15:30) 및 종가 전송(16:30) 종료 후의 시간외 세션(`afterMarket`)임. `closePrice`는 당일 정규장 확정 종가이며, `overMarketPriceInfo.overPrice`는 시간외 거래 가격임. quote_kind(`REGULAR_CLOSE` vs `AFTER_HOURS`)를 엄격히 분리하여 저장해야 함.
  3. **시가/고가/저가/거래량 부재**: basic 단일 엔드포인트에는 당일 open/high/low/volume이 포함되어 있지 않으므로 당일 봉 완성용으로 단독 사용할 수 없음.
  4. **수치 포맷**: 가격이 `"285,000"` 형태의 포맷팅된 문자열이므로 정규화 시 콤마 제거 및 유한 `Decimal` 파싱이 필수임.

### B. 한국 주식 일별 OHLCV (`naver_ohlcv.json` 분석)

- **수집 출처**: 네이버페이 증권 차트/시세 API (`https://m.stock.naver.com/api/stock/005930/price?page=1&pageSize=60` 추정)
- **확인 대상**: 삼성전자(005930), 2026-04-15 ~ 2026-09-23 일봉 시계열
- **실제 관측된 핵심 필드**:
  - 루트: `code="005930"`, `stockExchangeType="KRX"`, `periodType="dayCandle"`, `hasVolume=true`, `decimalUnit=0`
  - 개별 봉 (`priceInfos[]`):
    - `localDate`: `"20260923"` (8자리 날짜 문자열)
    - `closePrice`: `285500.0` (부동소수점/숫자)
    - `openPrice`: `284500.0`
    - `highPrice`: `285500.0`
    - `lowPrice`: `281000.0`
    - `accumulatedTradingVolume`: `18702740` (정수, 주식 수)
    - `foreignRetentionRate`: `46.55` (외인 지분율)
- **부족한 메타데이터 및 R07 적합성 분석**:
  1. **개장/마감 시각 및 타임존 부재**: `localDate`는 `"20260923"` 형태의 날짜만 제공됨. Bar 인터페이스 필수 필드인 `open_time`, `close_time`, `timezone`을 생성하기 위해 거래소 캘린더 규칙(`Asia/Seoul`, 개장 `09:00:00+09:00`, 마감 `15:30:00+09:00`)과 `availability_precision="DATE"`를 파서가 결합해야 함.
  2. **당일 미완성 봉(`is_complete`) 판정 필요**: 당일(2026-09-23) 봉의 경우, 장중(09:00~15:30)에 수집되면 가격이 실시간 변동 중인 미완성 봉(`is_complete=False`)임. 본 수집본은 16:47 이후 수집되어 확정된 종가이나, 장중 수집 시 미완성 봉이 SMA/RSI 등 기술적 지표 계산에 투입되지 않도록 `analysis_as_of` 및 세션 마감 시각 대조 로직이 필수적임.
  3. **가격 무결성 확인**: 최신 봉 기준 `low(281000) <= min(open, close)(284500) <= max(open, close)(285500) <= high(285500)` 조건을 완벽히 만족함.
  4. **수정주가(Split-adjusted) 메타데이터 결여**: 연속적인 가격 흐름으로 보아 수정주가가 적용된 시계열이나, 액면분할/병합 이력(`corporate_action_version`, 분할 비율, 적용일자)에 관한 메타데이터가 응답에 전혀 없음. Raw 가격과 혼합 봉 생성을 방지하고 `adjustment_mode="SPLIT_ADJUSTED"`로 명시해야 함. 배당이 재투자된 Total Return은 아님.
  5. **통화 및 수량 단위 누락**: 통화(`KRW`), 거래량 단위(`SHARES`)가 명시되지 않으므로 고정 메타데이터로 부여해야 함.
  6. **비거래일 갭**: 주말(예: 04/17 금 -> 04/20 월) 및 공휴일(예: 05/01 근로자의 날)은 응답에서 생략됨. R07에 따라 누락된 거래일을 임의의 이전 종가로 채우지 않고 유효 거래일 시계열로 보존해야 함.

### C. 웹 페이지 직접 스크래핑의 한계 및 URL 리다이렉트 (`source-checks-2026-09-23.md` 분석)

- **네이버 증권 리다이렉트 및 동적 렌더링**:
  - 기존 PC URL `finance.naver.com/item/main.naver?code=005930` 호출 시 `stock.naver.com/domestic/stock/005930/price`로 리다이렉트됨.
  - 리다이렉트된 페이지의 정적 HTML 응답에는 "KRX 제공·20분 지연" 문구만 존재하고, 실제 종목 가격 및 기준 시각이 렌더링되지 않음(클라이언트 사이드 JavaScript 렌더링 방식).
  - **결론**: 기존 구형 HTML 테이블 셀렉터(`table.no_today` 등)를 이용한 정적 HTML 파싱은 작동 불가함. 런타임 수집기는 (1) 내부 JSON API 엔드포인트를 직접 조회하거나, (2) 동적 렌더링 결과물이 번들된 payload를 소비하는 형태로 구현되어야 함.
- **Investing.com 미국 주식 페이지**:
  - `https://www.investing.com/equities/apple-computer-inc` 관측 결과 AAPL, NASDAQ, USD 식별자 확인.
  - 정규장 Closed 날짜와 별도 after-hours 시세가 명시적으로 구분되어 있음. 정규장 종가와 시간외 가격을 단일 quote로 합치지 않는 파서 분리 로직이 필수적임.

---

## 3. Gemini B 구현 컴포넌트 설계 계획

계약(CONTRACT-01) 확정 후 구현할 3개 신설 모듈 및 기존 모듈 보완 계획입니다.

### A. `runtime/investment_stack/providers/market_quotes.py` (신설)

1. **역할**: 실시간/지연/종가 시세 수집기 어댑터 및 정규화 파서.
2. **핵심 타입 및 파서 계약**:
   - `QuoteKind`: `REGULAR_SESSION`, `REGULAR_CLOSE`, `AFTER_HOURS`
   - `MarketQuote`:
     - `instrument_id`: 거래소:티커 (예: `KRX:005930`)
     - `price`: `Decimal` (유한 양수 검증)
     - `currency`: 통화 코드 (예: `KRW`, `USD`)
     - `quote_kind`: `QuoteKind`
     - `market_time`: 관측된 가격의 실제 체결/확정 시각 (ISO 8601 with timezone)
     - `delay_minutes`: 지연 시간 (실시간=0, 지연시 분 단위 양수)
     - `is_delayed`: bool
     - `raw_payload`: 원본 보존
   - `NaverBasicQuoteParser`:
     - `naver_basic.json`의 `closePrice`, `overPrice`, `localTradedAt`, `stockExchangeType`, `marketSessionType`을 파싱.
     - 통화는 거래소 코드(`KS` -> `KRW`)로 매핑.
     - 천 단위 쉼표 제거 후 유효 Decimal 변환.
     - 장 마감 후(`afterMarket`)의 경우 정규장 종가(`closePrice`, `REGULAR_CLOSE`)와 시간외 시세(`overPrice`, `AFTER_HOURS`)를 별도 관측값으로 추출.

### B. `runtime/investment_stack/providers/ohlcv.py` (신설)

1. **역할**: 역사적 OHLCV 일봉/분봉 수집기 및 R07 무결성 검증 파서.
2. **핵심 타입 및 파서 계약**:
   - `AdjustmentMode`: `RAW`, `SPLIT_ADJUSTED`, `TOTAL_RETURN`
   - `Bar`:
     - `open_time`, `close_time`: `datetime` (타임존 포함)
     - `open`, `high`, `low`, `close`: `Decimal`
     - `volume`: `Decimal` (>= 0)
     - `currency`: str
     - `is_complete`: bool (세션 완료 여부)
     - `adjustment_mode`: `AdjustmentMode`
   - `BarSet`:
     - `bars`: tuple[Bar, ...] (날짜/시간 오름차순 정렬)
     - `missing_sessions`: 누락된 거래일 목록 추적
   - `NaverOHLCVParser`:
     - `naver_ohlcv.json`의 `priceInfos` 배열 순회.
     - `localDate` ("YYYYMMDD")에 거래소 세션(09:00:00 ~ 15:30:00, Asia/Seoul) 결합.
     - 무결성 검사: `low <= min(open, close) <= max(open, close) <= high` 검증 (위배 시 해당 봉 부적격 격리).
     - 당일 봉 `is_complete` 판정: `as_of` 시점과 세션 마감 시각 비교 (장중이면 `is_complete=False`).
     - `adjustment_mode = SPLIT_ADJUSTED` 부여.

### C. `runtime/investment_stack/web_research/quote_sources.py` (신설) 및 기존 모듈 연동

1. **`quote_sources.py`**:
   - 시장별 공식/웹 엔드포인트 URL 빌더 및 HTTP 요청 헤더 정의.
   - 응답 실패/접근 제한 발생 시 다음 순위 후보로 fallback하는 라우팅 메커니즘.
2. **기존 `adapter.py` / `bundle.py` / `models.py` 보완**:
   - `WebResearchHit`에 `quote_kind`, `adjustment_mode`, `is_complete` 메타데이터 연동 지원.
   - 검색 스니펫(`search_snippet`), 출처 불명 페이지의 시세 채택 차단 규칙 유지.
   - 총괄 또는 외부에서 사전 캡처한 응답 번들(`WebResearchBundleBackend`)을 통한 결정론적 테스트 완벽 지원.

---

## 4. 총괄 후속 검증용 공개 HTTP Probe 엔드포인트 목록

총괄이 다음 단계에서 직접 실행(probe)할 수 있는 비개인화 공개 HTTP 엔드포인트 목록입니다. (개인정보 및 인증정보 없음)

```text
# 1. 한국 주식 (네이버페이 증권 공개 모바일/폴링 API)
# 삼성전자(005930) 기본 시세
GET https://m.stock.naver.com/api/stock/005930/basic
# 삼성전자(005930) 일별 OHLCV (최근 60영업일)
GET https://m.stock.naver.com/api/stock/005930/price?page=1&pageSize=60
# 삼성전자(005930) 실시간 폴링 시세
GET https://polling.finance.naver.com/api/realtime/domestic/stock/005930

# 2. 미국 주식 (공개 웹 페이지 / SEC 기본 엔드포인트)
# Investing.com Apple 시세 페이지 (정규/시간외 분리 확인용, 브라우저 User-Agent 필요할 수 있음)
GET https://www.investing.com/equities/apple-computer-inc
# SEC 공식 티커 매핑 파일 (User-Agent: Sample Company Name AdminContact@<sample company domain>.com 준수)
GET https://www.sec.gov/files/company_tickers.json

# 3. 가상자산 (Kraken 공개 REST API - 인증 불필요)
# BTC/USD 실시간 Ticker
GET https://api.kraken.com/0/public/Ticker?pair=XBTUSD
# BTC/USD 일별 OHLCV (최근 720개 봉)
GET https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440
```

---

## 5. 결론 및 대기 상태

- **요약**:
  - 네이버페이 증권의 동적 렌더링 전환으로 인해 일반 정적 HTML 스크래핑이 불가함을 확인하였으며, 총괄이 수집한 모바일 JSON API 응답(`naver_basic.json`, `naver_ohlcv.json`)의 세부 필드 구조를 완벽히 파악했습니다.
  - 누락된 메타데이터(통화 코드 `KRW` 부재, date-only 일봉의 세션 타임존 결합 필요, 당일 장중 봉의 `is_complete=False` 처리, 정규장 종가와 시간외 가격 분리, 수정주가 표기)에 대한 구체적 파서 처리 방안을 수립했습니다.
  - B 배정 범위(`providers/market_quotes.py`, `providers/ohlcv.py`, `web_research/quote_sources.py` 등)의 상세 설계를 완료했습니다.
- **다음 단계**:
  - 자체 코드 수정이나 추측성 구현을 진행하지 않고 즉시 작업을 종료합니다.
  - 총괄 및 공통계약(CONTRACT-01)의 기준 커밋 전달 및 구현 착수 지시를 대기합니다.
