# REVIEW-CODE-01 중간 재검토 — 979cc5e

- 독립 검토 task `01a0e30c-b115-7db0-9a6c-b05a962b2d8c`, 별도 worktree `89b8`.
- 직접 checkout/검토한 고정 SHA: `979cc5efb5d8bbb54e198ed9cb02ec891444c7de`.
- REQ-2026-09-23-v1 R01–R17 / DESIGN-2026-09-23-v0.1 및 D17/D18, 첫 패스 RC01–05와 수정 인계 기준.
- 첫 패스 산출물 세 파일이 9141474 이후 통합본의 blob과 같음을 확인한 뒤 worktree를 이동했다. 구현·원 테스트 수정, commit/push 없음. 실제 개인 DB·계정·주문 사용 없음.
- **중간 재검토이다.** B R15 패키지 및 C 네 모드 bundle이 아직 미통합이다. 최종 전체 REVIEW-CODE-01 또는 별도 VERIFY 완료가 아니다.

## 결론

기존 독립 반례 **5/5 PASS**, 기존 전체 **570 tests OK / skipped=1**를 직접 재실행했다. RC01의 FX 가중치, RC02의 Yahoo 명시 지연, RC03의 게시 후 오류 기록 실패는 첫 반례와 수정 경로를 확인했다. RC04·RC05는 원 반례를 차단하지만 더 넓은 입력에서 아래 두 P1이 남는다. 추가 회귀 **3 tests / 3 FAIL**을 소유자에게 회송했다.

### RC04-R1 [P1] 특정 지표의 누락된 기간을 다른 지표의 문맥으로 대체함

- 요구사항 R02, R09, R14, R17. 소유 A.
- 파일/행: `runtime/investment_stack/execution/analysis_modes.py:163–165`, `:181–185`.
- 현재 `reporting_context`는 각 metadata의 비어 있지 않은 값만 자산 전체 set에 합친다. `context_well_formed`는 이 합집합의 원소 수를 검사하므로 일부 지표의 metadata 누락을 감지하지 못한다.
- 재현: 최신 `R14EquityModeBundleIntegrationTests`의 정상 두 자산 fixture를 사용하고 KEYENCE의 **EPS 한 건**에서 `start`와 `restatement`만 제거한다. 다른 재무 지표는 양쪽 모두 2025-07-01~2026-06-30 ANNUAL/FY/US-GAAP/CONSOLIDATED/REPORTED/NONE을 유지한다.
- 실제: 비교 matrix.complete=True. 기간을 모르는 KEYENCE EPS 12와 FANUC EPS 12의 delta=0을 저장하고 보고한다. 전체 모드 PARTIAL은 이 잘못된 개별 비교를 차단하지 않는다.
- 기대: 비교에 실제 사용되는 **각 지표**의 선택 evidence와 기간·회계 문맥이 완전하고 일치해야 한다. 누락된 EPS 기간을 다른 매출/순익의 start로 채우지 않는다. 다른 충분한 지표는 제한적으로 비교할 수 있으나 EPS 및 그로부터 파생된 비교는 unavailable이어야 한다.
- 실행 재현: `review_code_01_interim_probes.py::test_rc04_missing_eps_period_cannot_borrow_other_metric_context`, FAIL (`eps unexpectedly found`). 실제 Phase4→Phase5→comparison→run.db 보고 경로, 합성 자료만 사용.

### RC05-R1 [P1] 13F 공개시점 수정 후에도 역순·누락·중복 분기가 유효 변화/지속성으로 남음

- 요구사항 R12, R13, R16. 소유 C.
- 파일/행: `runtime/investment_stack/institutional/compare.py:65`; `institutional/scoring.py:42–58`, `:100–104`, `:139`.
- `compare_portfolios`는 동일한 report_period만 거부하며 역순/비연속 기간은 승인한다. feature는 current_period cutoff와 두 공개시점만 확인하고, 정렬된 comparison마다 연속 보유 분기를 1씩 더한다. 중복·연속 분기 연결은 검사하지 않는다.
- 재현 A: 같은 기관/CUSIP, prior=2026-06-30 200주, current=2026-03-31 100주. 두 공시 공개가능시각 모두 2026-08-15, cutoff 2026-09-27. 실제 comparable=True, PIT=True, `quarterly_share_change_pct=-0.5`, `institutional_consensus_direction=-1`. 과거 분기를 현재처럼 비교하여 변화 방향을 뒤집는다.
- 재현 B: 2024Q1→2025Q1, 2025Q1→2026Q2 비교 두 개와 두 번째 비교의 동일 복제본을 공급. 실제 `consecutive_quarters_held=3`, PIT=True. 중간 분기 보유는 확인하지 못하고 현재 기간도 중복인데 연속성으로 표시한다.
- 기대: prior<current 및 quarter identity 검증, 분기 변화라면 실제 인접 분기 여부 검증, current quarter/filing 중복 제거·충돌 처리. 보유 지속성은 중간 분기 누락 시 끊겨야 한다. 공개시점이 과거인 사실만으로 기간 순서/연속성이 증명되지는 않는다.
- 실행 재현: `test_rc05_reversed_quarters_cannot_create_current_direction` 및 `test_rc05_duplicate_gap_comparisons_are_not_consecutive_quarters`, 둘 다 FAIL.
- 경계: 매매 gate는 DISABLED/UNVALIDATED 유지. 자동 주문이나 확정 매수 신호 발생을 주장하지 않는다. 이 재현은 DTO/계산 서비스 경계이며 SEC live 원문부터의 전 경로 재현은 아니다.

## 원 반례의 수정 확인

| ID | 직접 확인한 변화 | 중간 판정 |
|---|---|---|
| RC01 | converted_positions를 risk 분자에 전달. 동일 USD/JPY 경제 포트폴리오가 같은 위험값. scenario after도 해당 FX 환산 맵 사용 | 원 결함 수정 확인 |
| RC02 | calendar_aware evaluator에서 양수 delay_minutes를 먼저 거부, 원 15분 지연 fixture AVAILABLE 아님 | 원 provider 경로 수정 확인 |
| RC03 | 예외 handler/미등록 handler의 run-local logging도 보호. POSTED receipt를 갖는 FAILED 결과 반환 | 원 결함 수정 확인 |
| RC04 | 자산 단위 빈/불일치 context 거부 | 지표 단위 결속 미흡, RC04-R1 열림 |
| RC05 | 미래 current period 및 미상/미래 publication 차단, 자료 없으면 PIT=False/UNAVAILABLE | 기간 순서·지속성 미흡, RC05-R1 열림 |

## 주말 종가·검색 우회 재확인

합성 E2E·calendar·delay·web 회귀는 전체 suite에 포함되었다. 추가로 이 SHA의 **기본 factory/executor와 기본 HTTP transport**를 사용해 공개 Yahoo/Naver를 직접 조회하고 Phase4 저장→LiveDeepResearchRuntime→Phase5 입력을 실행했다. 임시 합성 run.db, 명시적으로 빈 EnvironmentCredentials, state_version=0/NONE:REVIEW 사용. 개인 DB 없음.

고정 analysis_as_of `2026-09-27T12:00:00+00:00`:

| 종목 | 실제 공개 응답에서 선택한 값 | 최종 freshness·세션 | Phase5 입력/고지 |
|---|---|---|---|
| NASDAQ:AAPL | USD 341.07 | LAST_VALID_CLOSE, 2026-09-25; 종가 관측16:00:01 ET, parser 공개가능20:00:01Z; nasdaq-2026-09-official-snapshot-v1 | current_price=341.07, 마지막 유효 종가·비실시간 고지 True |
| KRX:005930 | KRW 286500 | LAST_VALID_CLOSE, 2026-09-23; 정규장15:30 KST, 공개16:30 KST/07:30Z; krx-2026-chuseok-official-snapshot-v1 | current_price=286500, 마지막 유효 종가·비실시간 고지 True |

조회 URL은 [Yahoo chart](https://query1.finance.yahoo.com/v8/finance/chart/AAPL), [Naver basic](https://m.stock.naver.com/api/stock/005930/basic). Yahoo public_available_at은 regularMarketTime을 사용한 parser 해석이며 별도 공개시각 필드를 검증한 것으로 표현하지 않는다. Naver는 source의 closePriceSendTime에서 파생한다. 단발 live 성공은 지속 가용성이나 모든 시장 지원을 보장하지 않는다.

`WebResearchAdapter.fetch_current`는 검색 hit의 임의 거래소·시각 metadata로 가격을 승인하지 않고 UNAVAILABLE을 반환한다. pinned schedule의 누락 세션·범위 밖·잘못된 거래소/통화·미완성 bar, KRX 종가 공개 전 및 재개장 이후 차단은 직접 실행한 기존 회귀에서 통과했다. 공식 달력의 일반화/범위 확대를 새로 검증하지 않았으며 이전 보고서의 provenance 한계는 유지한다.

## 실행 명령·결과

인터프리터 `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`, `PYTHONPATH=runtime`; 이 격리 worktree 코드 사용.

1. `python docs/workflow/reviews/review_code_01_first_pass_probes.py -v`: 5 tests, OK (1.716s).
2. `python -m unittest discover -s tests -q`: 570 tests, OK (skipped=1, 54.093s).
3. `python -m build --no-isolation`: 이 SHA wheel/sdist 재생성 성공. 이어 `python -m unittest tests.test_packaging -q`: 5 tests, OK (skipped=1, 0.035s). 위 전체 suite 때의 기존 dist에 의존해 현 SHA package 검증을 주장하지 않도록 재생성 후 별도 검사했다.
4. `python docs/workflow/reviews/review_code_01_interim_probes.py -v`: 3 tests, **3 FAIL** (1.651s). 안전한 기대값 assert 실패이며 구현 오류를 그대로 재현하는 검토 코드다.
5. 두 공개 종목 기본 factory→Phase5 live 실행: 모두 정상 종료, 위 표의 값·날짜·freshness·고지 확인. 재무 provider/적정가 전체 live 성공을 의미하지 않는다.
6. `git diff --check`: 성공. tracked 구현 변경 없음.

미실행: 네 모드 통합 bundle의 최종 실행·개인 상태 loader 결속, B R15 최종 패키지/문서, 모든 공급자 live, 장기 calendar/13F 기간 외 검증, 실제 DB 장애/주문, 별도 최종 VERIFY. 수정 통합 최종 SHA를 받으면 이 검토 세션에서 다시 직접 확인한다.
