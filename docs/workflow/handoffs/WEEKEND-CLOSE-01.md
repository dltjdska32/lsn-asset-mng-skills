# WEEKEND-CLOSE-01 — 2026-09-27 사용자 시세 보정

## 기준과 판정

- 사용자 지시: 2026-09-27 일요일에는 조회일과 응답 가격 날짜가 다르다는 이유만으로 종가를 버리지 말고, 각 거래소의 마지막 유효 거래일 종가인지 확인해 계산에 사용한다. 이 지시가 이전의 단순 경과 시간에 따른 stale 표현보다 우선한다.
- 공개 소스: AAPL 거래소인 [Nasdaq Trader 2026 거래 캘린더](https://nasdaqtrader.com/Trader.aspx?id=Calendar)와 [Nasdaq 2026-09-25 거래일 공지](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-685), [NYSE 2026 휴장·거래시간](https://www.nyse.com/trade/hours-calendars), [KRX 2026 추석 전 마지막 매매일 9/23 및 재공지일 9/28 공고](https://kind.krx.co.kr/external/dst/notice/11637/%5B%ED%95%9C%EA%B5%AD%EA%B1%B0%EB%9E%98%EC%86%8C%5D%202026%EB%85%84%20%EC%98%AC%EB%B9%BC%EB%AF%B8%EA%B3%B5%EC%8B%9C%20%EC%95%88%EB%82%B4.pdf), [행정안전부 2026 추석 연휴 9/24~27](https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=129490), [KRX 공휴일·주말 휴장 규칙](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp).
- 위 자료에서 9/27 기준 NASDAQ의 마지막 완료 정규 세션은 9/25, KRX의 마지막 완료 정규 세션은 9/23으로 추론한다. 이 추론만으로 개별 Yahoo/Naver 응답의 종목·통화·가격 종류·종가 시각·조정 여부가 입증되지는 않는다. `LAST_VALID_CLOSE` 계산 허용은 런타임 검증 후에만 확정한다.
- 2026-09-27 공개 API 직접 재조회: Yahoo chart AAPL은 `NMS`/USD, `regularMarketTime=1790366401`(9/25 16:00:01 ET), `regularMarketPrice=341.07`, 지연 필드는 없음. Naver basic 005930은 `KS`, `closePrice=286,500`, `localTradedAt=9/23 20:20:21 KST`, `marketSessionType=afterMarket`, `endTime=1530`, `closePriceSendTime=1630`, `delayTime=0`이었다. Naver의 15:30 종가 시각은 원문 체결시각이 아니라 `closePrice`와 거래소 정규장 종료시각에서 파생한 값이다. 조회·파싱 성공은 계산 적격 판정이 아니다.

## 배정과 결함

- 기준 root `f055546`(R06 통합 및 전체 511 OK/skip1). B GPT-6 Luna Medium task `01a0e2a5-b0ff-7690-b818-5652533aa0c1`의 별도 72d3 worktree/새 branch에서 이번에 한해 `freshness/engine.py`·`freshness/models.py`, 신규 calendar 및 B 소유 `providers/market_quotes.py`·전용 테스트를 단일 소유로 수정. A task `01a0e2a4-f627-7610-8cbf-fabe9bad1a70`는 R14 파일에 집중하며 freshness를 수정하지 않는다. C 소유 파일 불변.
- 발견한 현재 결함: `FreshnessEngine.assess`는 `market_session`이 CLOSED/HOLIDAY이고 관측에 임의 `market_session_date`만 있으면 날짜가 지난주여도 `LAST_VALID_CLOSE`를 반환한다. 반대로 현재 기본 20분/1일 정책을 그대로 쓰면 휴장 중 마지막 완료 세션 종가를 stale로 분류할 수 있다. B R06은 freshness evaluator 없을 때 안전하게 UNAVAILABLE이나, 거래소 일정 기반 evaluator의 생산 연결은 미완이다.
- 완료 조건: 출처 있는 거래소별 일정·시간대와 session close를 as-of 기준으로 판정; 9/27의 NASDAQ 9/25와 KRX 9/23 유효 종가 허용; 중간 거래일 누락, 월요일 개장/완료 후 과거 종가, 몇 주 전 가격, 잘못된 시장, 24/7 코인, 미래/미완성 봉, 달력 근거 부재 차단; 계산 수치에는 종가 시각과 '마지막 유효 거래일 종가' 라벨. 합성 반례, 공개 응답 재검증, root 직접 회귀 및 이후 별도 독립 검토/최종 검증.

## 2026-09-27 통합 후 직접 확인

- A의 Yahoo 공개 요청 헤더 수정 source `fc189a0`을 root `8640632`에 반영했다. 총괄의 **실제 기본** `build_default_provider_executor()` 실행에서 Yahoo AAPL HTTP 200/`341.07 USD`/9월25일 16:00:01 ET, Naver 삼성 HTTP 200/`286500 KRW`/9월23일 정규장 파생 15:30 KST를 각각 선택했다. 선택 observation을 공통 `assess_current_price_observation`으로 다시 검사한 결과 둘 다 `LAST_VALID_CLOSE`(Nasdaq 마지막 완료 세션 9/25, KRX 추석 전 마지막 완료 세션 9/23)였다. 담당 집중 8/8 PASS. 이 공개 조회는 특정 시점의 가용성 증거이며 다른 주말이나 공급자 지속 가용성을 보증하지 않는다.

- A R01 후속 source `2c3a1d8`·`1c4c6fe`·`e65f6f6`을 root `c6e63d9`까지 통합하고, 총괄은 합성 Yahoo/Naver의 Phase4→run.db→Phase5→한국어 보고서 29/29 및 전체 564 OK(skip1)를 직접 확인했다. Yahoo의 명시적인 `exchangeDataDelayedBy>0`은 종가 판정에서 차단한다. 아직 별도 독립 검토의 최종 재검토와 다른 최종 검증은 남아 있다.
- 헤더 수정 전 실제 기본 provider 실행에서 KRX 005930은 Naver `LAST_VALID_CLOSE`로 선택되었으나 NASDAQ:AAPL은 Yahoo HTTP 429로 `CANDIDATES_EXHAUSTED`였다. scoped truststore 직접 진단에서 헤더 없는 Yahoo 요청은 HTTP 429, `User-Agent: Mozilla/5.0` 요청은 HTTP 200(3546 bytes)이었다. 이는 종가 시각 적격성 오류가 아니라 전송 헤더 결손으로, 위 `8640632` 재조회에서 해결을 확인했다.

- B source `86161c3`·`d1052d1`을 root `6b36c4b`·`02a5710`으로 통합했고, 총괄이 focused 44/44 및 전체 543 OK(skip1)를 실행했다. B 인계는 `LUNA-B-SESSION-FRESHNESS.md`.
- root의 scoped TLS 공개 조회로 Yahoo AAPL `341.07`(9/25 16:00:01 ET), Naver 삼성 `286,500`(9/23 정규장 파생 종가 15:30 KST, 공개가능 16:30)을 재조회한 뒤 parser→pinned calendar→freshness evaluator에 직접 넣었다. 두 응답 모두 `LAST_VALID_CLOSE`, eligible=True였다. 이는 현재가 실시간 판정이 아니다.
- B 단독 통합 시점에는 기본 provider factory와 목적별 선택, Phase5 계산·보고 연결이 A 소유 후속 작업이었다. 이후 A의 합성 Phase4→5→6 및 위 실제 기본 provider 조회까지 검증했다. 일곱 모드 전체의 실데이터 연결 완료를 뜻하지 않는다. pinned 일정은 해당 2026년 9월 구간으로 제한되어 다른 주말은 새 공식 일정 근거 전에는 fail closed다. 독립 전체 검토와 다른 최종 검증은 이후 시행한다.

과거 handoff의 '9/27보다 오래되어 현재가 아님'은 실시간 여부만을 뜻하며, 마지막 유효 거래일 종가의 계산 불가 결론으로 사용하지 않는다.
