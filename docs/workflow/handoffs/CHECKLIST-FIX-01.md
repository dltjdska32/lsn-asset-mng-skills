# 점검표 판정과 수정

- 기준 HEAD: `feadc133347ddcb40fce83fc2089810f3e78d586`. 브랜치: `cursor/usable-r11-binding`. 미커밋 USABLE-R11 작업 트리를 유지했다. 실제 개인 DB와 주문은 사용하지 않았다.
- FANUC 7,000엔, 미쓰비시 4,600엔, 경험적 추매가는 입력하지 않았다.

## 판정

| 항목 | 판정 |
|---|---|
| D12 80/75/70, 8%, 10%, 3회 분할, 축소 검토 | 이미 구현. 유지 |
| 저장 원문 재파싱, 없으면 WAIT | 이미 구현. 유지 |
| 예약금·미체결 차감, 미선언을 0으로 보지 않음 | 이미 구현. 유지 |
| 미국/한국 고정 달력의 주말 마지막 종가 | 이미 구현. 유지 |
| 7개 모드, 자동 주문 금지, 합성 조건부 수량 | 이미 구현. 유지 |
| 시세 fallback 후보 등록 | 이미 구현. 호스트는 라이브 조회를 하지 않음 |
| 검색시각과 체결시각 분리, FRESH/DELAYED/LAST_VALID_CLOSE/STALE | 이미 구현. 정규장 현재가로 시간외를 쓰지 않도록 보강 |
| 단일 출처를 복수 검증처럼 표현 | 실제 결함. 단일 출처라고 적고, 가격이 다르면 보류 |
| 해시=공급자 진위 | 실제 과장. 문구를 저장 본문 무결성으로 고침 |
| 일본 JPX/Yahoo Japan 후보를 현재가로 승격 | 실제 결함. 미검증 출처와 JPX 본문은 현재가가 되지 않음. 공식 거래일 달력은 여전히 없음 |
| DCF가 FCFF/FCFE 없이 순부채를 차감 | 실제 결함. 원문에 FCFF 또는 FCFE가 있을 때만 행동용 적정가. FCFE와 순부채 차감은 함께 쓰지 않음 |
| OCF−CAPEX를 잉여현금흐름으로 표시 | 실제 과장. 영업현금흐름에서 자본적지출을 뺀 값으로 표시. SBC·운전자본·이자·리스·만기는 추정하지 않음 |
| 뉴스 materiality가 보유 종목 선택만 수행 | 별도 경로가 없었음. 원문이 valuation/thesis 영향을 밝힐 때만 판정. 가격은 만들지 않음 |
| 추매가를 위험·변동성·평단으로 다시 계산 | 요구사항 충돌(D17). 승인된 80/75/70을 유지. 비중과 가용현금은 예산·수량에만 반영 |
| 1H/당일/5D/거래량 급락, NO_ALERT, 데이터센터, 고객 집중, 가이던스 숫자 diff, 알림 게이트 | 이 점검에서는 구현하지 않음. 이후 `handoffs/MONITOR-01.md`가 검토 전용으로 추가했고 D12 숫자는 유지 |
| 환율 | 이미 구현. 검증된 FX 본문이 있을 때만 변환 |
| 공식자료 우선과 검증 안 된 숫자의 valuation 투입 | 이미 구현. 뉴스 숫자만으로 적정가를 열지 않음 |

## 변경 파일

- `runtime/investment_stack/evidence/source_receipt.py`
- `runtime/investment_stack/decisions/policy_b_market.py`
- `runtime/investment_stack/reporting/policy_b_briefing.py`
- `runtime/investment_stack/providers/market_quotes.py`
- `runtime/investment_stack/web_research/quote_sources.py`
- `runtime/investment_stack/calculations/equity.py`
- `runtime/investment_stack/execution/selected_asset_research.py`
- `runtime/investment_stack/materiality/event_gate.py`
- `tests/integration/test_usable_policy_binding.py`
- `tests/unit/test_event_materiality.py`
- `docs/workflow/decisions.md`
- `docs/workflow/tasks.md`

## 테스트

첫 전체 실행은 패키징 allowlist 1건이 실패했다. 새 `event_gate.py`가 기존 `dist` wheel에 없었다.

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
Ran 706 tests in 120.979s
FAILED (failures=1, skipped=1)
```

이어서 `.\.venv\Scripts\python.exe -m build --outdir dist`로 wheel/sdist를 다시 만든 뒤 같은 명령을 다시 실행했다.

```text
Ran 706 tests in 122.911s
OK (skipped=1)
```

종료 코드 0. 이전 704 통과 기록은 이 검증에 사용하지 않았다. `investment-stack-for-gpt.zip`은 이 작업에서 다시 만들지 않았다. 그 파일은 여전히 이 작업 트리와 다르다.

## 남은 WAIT

라이브 공급자 진위, 실제 개인 금액, 2026-09 고정 달력 밖, 일본 공식 거래일, 기간 외 13F. 급락·할인 검토는 이후 `MONITOR-01`이 행동 가격과 분리해 추가했다.
