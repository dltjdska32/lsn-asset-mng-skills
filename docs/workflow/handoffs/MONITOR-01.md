# 검토 전용 감시와 시세 본문 저장

- 기준 HEAD: `feadc133347ddcb40fce83fc2089810f3e78d586`. 브랜치: `cursor/usable-r11-binding`. 미커밋 USABLE-R11 작업 트리를 유지했다. 커밋하지 않았다.
- 실제 개인 DB, 자동 주문, 개인 금액 생성은 하지 않았다.

## 결정

D12 진입가·예산·수량은 원문 기준 적정가의 80/75/70이다. 급락·알림·뉴스 중복·데이터센터·고객 집중·가이던스 차이·변동성 참고가는 그 숫자를 바꾸지 않는 검토다. 임계값은 사용자 선택지 없이 코드에 고정했다.

- 완료된 봉이 2개 미만이면 급락 상태는 `WAIT`.
- 세션 수익률 −5% 이하, 5세션 −8% 이하, 또는 1봉 −3% 이하이면서 직전 거래량 중앙값의 2배 이상이면 `DROP_REVIEW`.
- 변동성 참고가는 일간 수익률 표준편차와 5% 중 작은 비율만 빼서 보여 준다. 봉이 부족하면 가격을 만들지 않는다.
- 같은 사건 ID나 정규화한 URL이 반복되고 급락 검토가 없으면 `NO_ALERT`.
- 고객 비중은 공시 합계의 20% 이상이면 이름만 표시한다. 데이터센터 필드가 없으면 `WAIT`.
- 가이던스 차이는 이전 값과 현재 값이 둘 다 있을 때만 계산한다.
- `refresh_market_bodies`가 참일 때만 미국·한국 공개 시세 본문을 가져온다. 저장 행은 선택되지 않으므로 D12 숫자를 열지 않는다. 일본 종목은 요청하지 않는다.
- 일본 공식 거래일 목록은 넣지 않았다. 13F는 저장 플래그가 있어도 `DISABLED`다.

## 변경 파일

- `runtime/investment_stack/monitoring/review.py`
- `runtime/investment_stack/execution/quote_refresh.py`
- `runtime/investment_stack/reporting/policy_b_briefing.py`
- `runtime/investment_stack/web_research/adapter.py`
- `runtime/investment_stack/cli.py`
- `tests/unit/test_monitoring_review.py`
- `docs/workflow/decisions.md` D17

## 검증

`python -m build --outdir dist` 이후 `.venv`에서 `python -m unittest discover -s tests`.

결과: **713 OK, skip 1**, 133.099초. 이전 706 결과는 이 변경의 검증으로 쓰지 않는다.

독립 검토와 최종 검증은 이 변경에 대해 다시 실행하지 않았다.

## 남은 대기

라이브 공급자 진위, 사용자가 직접 넣어야 하는 개인 금액, 2026-09 고정 달력 밖의 거래일, 일본 공식 세션, 기간 외 13F 채택. 조회한 시세 본문은 기존 재파싱·선택 경로를 통과하기 전에는 현재가가 아니다.
