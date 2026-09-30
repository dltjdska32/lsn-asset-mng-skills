# USABLE-R11 독립 검토 01

## 범위

- 역할: 독립 검토자(구현자 아님). 커밋·push·runtime/tests 수정 없음. 본 파일만 작성.
- 브랜치: `cursor/usable-r11-binding`
- 기준 커밋(exact HEAD): `feadc133347ddcb40fce83fc2089810f3e78d586`
- 검토 대상: `git diff feadc133 -- runtime tests` 및 untracked `source_receipt.py`, `host.py`, migrations `v0003`/`v0004`, `reserves.py`, `auxiliary_context.py`, `test_usable_policy_binding.py`
- 제외: `investment-stack-for-gpt.zip`, 실제 개인 DB, 자동 주문, 라이브 시세 호출, 개인 금액 기재
- 문서(`handoffs`/`tasks` 등)는 참고만 했고 증명으로 쓰지 않음

## 실행한 것

프로젝트 `.venv` Python:

1. `python -m unittest tests.decisions.test_policy_b_market tests.integration.test_usable_policy_binding -v` → **26 OK**
2. 합성 temp DB/원장 집중 프로브 10건(임시 스크립트, 저장소에 남기지 않음) → **10/10 PASS**
3. 전체 704 스위트는 구현자 보고를 신뢰하고 반복하지 않음

## 실패 모드 프로브 결과

| # | 실패 모드 | 결과 | 관찰 |
|---|-----------|------|------|
| 1 | URL/제공자 이름만으로 시세·DCF verified | **차단** | HTTPS URI·`yahoo_finance`/`yahoo_chart`만 있는 synthetics: `quote_per_share is None`, 사유에 `authenticated source-content receipt` |
| 2 | 다른 종목·통화·시각·세션 본문으로 검증 | **차단** | 본문 심볼 `ZZZ` → 시세 None; `verify_quote_body`에서 KRW·다른 observed_at·잘못된 session_date 모두 False |
| 3 | 주말 마지막 종가를 실시간/FRESH로 표시 | **차단** | 적격 `LAST_VALID_CLOSE` + Yahoo 본문 시 `quote_kind=LAST_VALID_CLOSE`, 라벨 `비실시간 마지막 유효 거래일 종가`; 동일 행을 FRESH로 위장하면 재평가 불일치로 None |
| 4 | 예약 커버리지 없음 → 예약 0·투자가능 현금 개방 | **차단** | `list_cash_reservations` → `(False, ())`; `investable_cash is None`, `eligible_for_policy_sizing=False`, reserve 관련 unavailable_reasons |
| 5 | 호출자 `PolicyBResult`/`sizing`만으로 수량 개방 | **차단** | 호출자 CONDITIONAL/CONDITIONAL_NON_POSTING 객체를 넘겨도 run/ledger 없으면 `진입 가격·금액·수량 대기`, metadata `WAIT` |
| 6 | 논지 훼손인데 추가 수량 출력 | **차단** | `thesis_impaired=true` 원문 결속 시 `추가매수 중지`, `조건부 진입`/`수량 ` 없음 |
| 7 | 호스트/CLI가 원장 게시·라이브 조회 | **차단** | `_refuse_live_fetch`가 RuntimeError; 구성 호스트 execute 후 transaction_id·state_version 불변; 경로 없는 CLI exit 3 + UNSUPPORTED |
| 8 | 13F 점수를 주문 조건으로 사용 | **차단** | `check_13f_trade_gate` → `DISABLED`; 보조 섹션·조건부 브리핑에 매매 조건 아님 문구; `orders_posted=False` |
| 9 | 숨은 DCF 기본값(beta/ERP 등)으로 적정가 | **차단** | body에 `beta`/`erp`/`default`/`equity_risk_premium` → `unsupported default field`; excerpt 없으면 실패; source_documents 없는 바인딩만으로 `fair_value_per_share is None` |
| 10 | 해시 불일치·동일 evidence 두 문서 행 | **차단** | 잘못된 sha256 또는 중복 row → `load_source_payload` None, 시세 verified 없음 |

## P1 / P2

- **P1 (거짓 행동 숫자·주문·개인 데이터 유출): 없음** — 위 프로브와 집중 테스트에서 재현하지 못함.
- **P2 (잘못된 WAIT/숫자 경계): 없음** — 같은 범위에서 재현하지 못함.

발명한 실패는 없음. 코드만 읽고 실행하지 않은 가설은 목록에 넣지 않았다.

## 닫힌 채로 확인한 WAIT 경계

다음 경계는 이 작업 트리에서 계속 닫혀 있음을 확인했다.

- 저장 본문(source receipt) 없는 시세/DCF → verified Money·행동 숫자 개방 안 함
- `reservation_coverage` 미선언 → 예약을 0으로 취급하지 않음, 투자가능 현금·사이징 미개방
- 호출자 정책/사이징 객체만으로는 브리핑 숫자 미개방
- 구성 없는 CLI → 기존처럼 실패(exit 3), 주문/라이브 조회 없음
- 13F 게이트 DISABLED, 차트·13F는 매매 수량 조건이 아님
- 논지 훼손 시 추가매수 수량 미출력

의도적으로 남는(제품 미완) WAIT — 인계와 일치, 이번 프로브에서 “잘못 열린” 증거는 없음:

- 라이브 공급자 본문의 진위 증명
- 실제 개인 금액 입력
- 2026-09 고정 달력 밖의 거래일
- 기간 외 13F 채택
- 포트폴리오 모드에서 저장 연구 스펙 없는 차트 숫자

## 판정

지정 10개 실패 모드에 대한 집중 재현 결과, **새 P1/P2 없음**. 저장 원문 결속 경계는 합성 temp DB/원장에서 닫힌 상태로 확인됐다. 별도 최종 검증 세션의 전체 suite·패키징 대조는 이 검토에 포함하지 않았다.
