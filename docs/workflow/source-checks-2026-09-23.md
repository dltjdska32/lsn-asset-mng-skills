# 공개 원문 사전 확인 (총괄)

이 기록은 2026-09-23 웹 도구로 해당 페이지를 직접 연 결과이며, 런타임 HTTP adapter의 성공이나 현재 투자 가격 검증을 대신하지 않는다. 검색 snippet 가격은 입력하지 않았다. 구현 담당자는 아래 원문과 실제 HTTP 응답을 별도로 확인한다.

## 직접 HTTP 후속 실증

2026-09-23 07:44–07:48 UTC, 총괄 실행. Python3.14 기본 ssl은 `SSLCertVerificationError / Basic Constraints of CA cert not marked critical`로 세 URL 모두 실패. TLS 검증을 끄지 않고 Windows native TLS 경로(Invoke-WebRequest)에서 SEC CompanyFacts AAPL 200(3,789,099 bytes), SEC Berkshire submissions 200(161,264 bytes), Naver 새 주가 HTML 200(139,974 bytes), Naver mobile basic API 200(4,019 bytes)을 받았다. Investing AAPL 직접 요청은 403. 웹 도구의 접근 성공과 직접 HTTP 결과가 다름을 유지한다.

실제 읽은 공개 endpoint: `https://m.stock.naver.com/api/stock/005930/basic`, `https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json`, `https://data.sec.gov/submissions/CIK0001067983.json`. User-Agent는 기존 `investment-stack/0.1 local-research`, 인증·개인DB 사용 없음. Raw 응답/receipt는 ignored workspace/runs/live-source-checks에 보존한다.

Naver basic 실제 필드: itemCode/stockName/stockExchangeType(code KS, zoneId Asia/Seoul, name KOSPI)/closePrice/localTradedAt/delayTime/marketStatus/marketSessionType/overMarketPriceInfo. 정상 KRX 시간 이후 응답에 별도 AFTER_MARKET가 존재하므로 session/venue를 혼합하지 않는다. currencyType 필드는 없었다. 화폐 단위는 확인된 instrument listing mapping을 별도 근거로 사용하거나 unavailable로 남겨야 한다. 새 PC HTML에는 가격 데이터가 없어 그 HTML만으로 quote 확정 불가.

SEC submissions 실제 recent에서 13F-HR accession `0001193125-26-352200`, reportDate `2026-06-30`, filingDate `2026-08-14`, acceptanceDateTime `2026-08-14T20:05:04.000Z`, primaryDocument `xslForm13F_X02/primary_doc.xml`를 확인했다. 이는 공시목록 응답 실증이며 information table 원문·정정·비교 파서 검증은 아직 아니다.

Antigravity print mode는 read_url도 soft-deny하고 SUCCESS/empty response를 반환했다. Gemini에게 허용되지 않은 web 도구를 반복 요청하지 않는다. 총괄이 직접 source를 확인해 사본/receipt를 제공하고 Gemini는 자기 worktree의 파일 read/write로 구현한다. 전역 권한 완화 없음.

추가 실증: `.venv` truststore0.10.4 설치 후 Python `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`의 verify_mode=CERT_REQUIRED(2), check_hostname=True 상태에서 Naver basic과 SEC CompanyFacts 모두 HTTP200(07:49:54–55UTC). 글로벌 inject나 검증 해제는 하지 않았다. 공통 transport에 scoped context를 적용하고 Windows 패키지 의존성에 반영할 기술적 해결안이다. [공식 truststore API](https://truststore.readthedocs.io/en/latest/).

Naver `https://api.stock.naver.com/chart/domestic/item/005930?periodType=dayCandle` 직접 HTTP200(19,282 bytes). code/stockExchangeType(KRX)/periodType/dayCandle/hasVolume/decimalUnit/priceInfos와 localDate·open/high/low/closePrice·accumulatedTradingVolume를 확인했다. 원 숫자 JSON token을 Decimal로 읽어야 한다. payload에 수정주가/분할근거·완성봉/정확한 close timestamp가 없으므로 이 정보가 검증되지 않은 series를 무조건 분석 적격으로 만들지 않는다. 마지막 localDate는 20260923이었으며 현재/미완성봉 여부는 별도 캘린더 검증 조건이다.

SEC 위 accession의 Archives index.json·primary_doc.xml 직접 HTTP는403. 웹 도구도 각각 접근불가·XML content-type 미지원이었다. submissions 성공을 information-table 수집 성공으로 보고하지 않는다.

2026-09-23 07:53:56UTC: verified Python truststore context로 `https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1mo` HTTP200(3,441bytes), `https://api.exchange.coinbase.com/products/BTC-USD/ticker` HTTP200(186bytes). Yahoo에는 currency=USD, symbol=AAPL, exchangeName=NMS/fullExchangeName=NasdaqGS, exchangeTimezoneName=America/New_York, regularMarketTime/regularMarketPrice와 currentTradingPeriod pre/regular/post, timestamp 배열, indicators.quote/adjclose가 있었다. closed regular 값과 fulldayPrice를 혼합하지 않는다. delay/calendars/splits completeness는 응답 성공만으로 확인되지 않았다. Coinbase에는 price·bid·ask·size·volume·trade_id·time(나노초 UTC)이 있었고 이는 Coinbase BTC-USD 거래소 가격이지 전시장 합성가가 아니다. 원 payload는 ignored source 입력으로 담당 B에게 전달한다. source를 실증했지만 아직 adapter/eligibility/indicator까지 검증한 것은 아니다.

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): Company Facts와 company concept의 단위별 배열, submissions의 CIK 10자리·recent 및 추가 files 구조를 확인했다. 프레임의 달력 정렬이 동일한 실제 재무 기간을 보장하지 않는다는 주의사항이 있다. parser는 start/end·unit·filed·accession을 보존해야 한다.
- [SEC 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f): 2026-03-06 갱신 표기. 2023-01-03 적용 형식은 value를 달러로 반올림하며 과거 천 달러 형식과 다르다. schema/version과 제출 원문에 기반해 scale을 판정해야 한다. 정정 종류와 confidential omission 처리도 해당 원문을 참조한다.
- [SEC Developer Resources](https://www.sec.gov/about/developer-resources): 자동 수집은 공식 접근 정책을 따른다. 로그인/API키 존재를 가정하거나 User-Agent 연락처를 발명하지 않는다. 접근 제한 발생 시 제한으로 기록한다.
- [Npay 삼성전자 페이지](https://stock.naver.com/domestic/stock/005930/price): 기존 finance.naver.com/item/main.naver?code=005930 URL이 이 새 URL로 redirect되었다. 도구가 반환한 HTML 텍스트에는 KRX 제공·20분 지연 표기가 있지만 종목 가격/기준시각이 없었다. 기존 구형 HTML selector를 접근 확인 없이 production 성공으로 간주하지 않는다.
- [Investing Apple 페이지](https://www.investing.com/equities/apple-computer-inc): AAPL·NASDAQ·USD·정규장 Closed 날짜와 별도 after-hours 가격/시간 표기가 실제 응답에서 확인되었다. 표면 시간의 timezone/연도·delay/세션 의미를 파서에서 명시적으로 검증해야 하며 정규장 종가와 시간외를 혼합하지 않는다. 이 단일 페이지 접근으로 전체 시장 coverage나 runtime 자동수집 성공을 주장하지 않는다.
