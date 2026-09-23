# 공개 원문 사전 확인 (총괄)

이 기록은 2026-09-23 웹 도구로 해당 페이지를 직접 연 결과이며, 런타임 HTTP adapter의 성공이나 현재 투자 가격 검증을 대신하지 않는다. 검색 snippet 가격은 입력하지 않았다. 구현 담당자는 아래 원문과 실제 HTTP 응답을 별도로 확인한다.

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): Company Facts와 company concept의 단위별 배열, submissions의 CIK 10자리·recent 및 추가 files 구조를 확인했다. 프레임의 달력 정렬이 동일한 실제 재무 기간을 보장하지 않는다는 주의사항이 있다. parser는 start/end·unit·filed·accession을 보존해야 한다.
- [SEC 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f): 2026-03-06 갱신 표기. 2023-01-03 적용 형식은 value를 달러로 반올림하며 과거 천 달러 형식과 다르다. schema/version과 제출 원문에 기반해 scale을 판정해야 한다. 정정 종류와 confidential omission 처리도 해당 원문을 참조한다.
- [SEC Developer Resources](https://www.sec.gov/about/developer-resources): 자동 수집은 공식 접근 정책을 따른다. 로그인/API키 존재를 가정하거나 User-Agent 연락처를 발명하지 않는다. 접근 제한 발생 시 제한으로 기록한다.
- [Npay 삼성전자 페이지](https://stock.naver.com/domestic/stock/005930/price): 기존 finance.naver.com/item/main.naver?code=005930 URL이 이 새 URL로 redirect되었다. 도구가 반환한 HTML 텍스트에는 KRX 제공·20분 지연 표기가 있지만 종목 가격/기준시각이 없었다. 기존 구형 HTML selector를 접근 확인 없이 production 성공으로 간주하지 않는다.
- [Investing Apple 페이지](https://www.investing.com/equities/apple-computer-inc): AAPL·NASDAQ·USD·정규장 Closed 날짜와 별도 after-hours 가격/시간 표기가 실제 응답에서 확인되었다. 표면 시간의 timezone/연도·delay/세션 의미를 파서에서 명시적으로 검증해야 하며 정규장 종가와 시간외를 혼합하지 않는다. 이 단일 페이지 접근으로 전체 시장 coverage나 runtime 자동수집 성공을 주장하지 않는다.
