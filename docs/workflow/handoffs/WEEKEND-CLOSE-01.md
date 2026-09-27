# WEEKEND-CLOSE-01 — 2026-09-27 사용자 시세 보정

## 기준과 판정

- 사용자 지시: 2026-09-27 일요일에는 조회일과 응답 가격 날짜가 다르다는 이유만으로 종가를 버리지 말고, 각 거래소의 마지막 유효 거래일 종가인지 확인해 계산에 사용한다. 이 지시가 이전의 단순 경과 시간에 따른 stale 표현보다 우선한다.
- 공개 소스: AAPL 거래소인 [Nasdaq Trader 2026 거래 캘린더](https://nasdaqtrader.com/Trader.aspx?id=Calendar)와 [Nasdaq 2026-09-25 거래일 공지](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-685), [NYSE 2026 휴장·거래시간](https://www.nyse.com/trade/hours-calendars), [행정안전부 2026 추석 연휴 9/24~27](https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=129490), [KRX 공휴일·주말 휴장 규칙](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp).
- 위 자료에서 9/27 기준 NASDAQ의 마지막 완료 정규 세션은 9/25, KRX의 마지막 완료 정규 세션은 9/23으로 추론한다. 이 추론만으로 개별 Yahoo/Naver 응답의 종목·통화·가격 종류·종가 시각·조정 여부가 입증되지는 않는다. `LAST_VALID_CLOSE` 계산 허용은 런타임 검증 후에만 확정한다.

## 배정과 결함

- 기준 root `f055546`(R06 통합 및 전체 511 OK/skip1). B GPT-6 Luna Medium task `01a0e2a5-b0ff-7690-b818-5652533aa0c1`의 별도 72d3 worktree/새 branch에서 이번에 한해 `freshness/engine.py`·`freshness/models.py`, 신규 calendar 및 B 소유 `providers/market_quotes.py`·전용 테스트를 단일 소유로 수정. A task `01a0e2a4-f627-7610-8cbf-fabe9bad1a70`는 R14 파일에 집중하며 freshness를 수정하지 않는다. C 소유 파일 불변.
- 발견한 현재 결함: `FreshnessEngine.assess`는 `market_session`이 CLOSED/HOLIDAY이고 관측에 임의 `market_session_date`만 있으면 날짜가 지난주여도 `LAST_VALID_CLOSE`를 반환한다. 반대로 현재 기본 20분/1일 정책을 그대로 쓰면 휴장 중 마지막 완료 세션 종가를 stale로 분류할 수 있다. B R06은 freshness evaluator 없을 때 안전하게 UNAVAILABLE이나, 거래소 일정 기반 evaluator의 생산 연결은 미완이다.
- 완료 조건: 출처 있는 거래소별 일정·시간대와 session close를 as-of 기준으로 판정; 9/27의 NASDAQ 9/25와 KRX 9/23 유효 종가 허용; 중간 거래일 누락, 월요일 개장/완료 후 과거 종가, 몇 주 전 가격, 잘못된 시장, 24/7 코인, 미래/미완성 봉, 달력 근거 부재 차단; 계산 수치에는 종가 시각과 '마지막 유효 거래일 종가' 라벨. 합성 반례, 공개 응답 재검증, root 직접 회귀 및 이후 별도 독립 검토/최종 검증.

현재 상태: 구현·직접 검증 **진행 중**. 과거 handoff의 '9/27보다 오래되어 현재가 아님'은 실시간 여부만을 뜻하며, 마지막 유효 거래일 종가의 계산 불가 결론으로 사용하지 않는다.
