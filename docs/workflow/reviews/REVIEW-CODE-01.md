# REVIEW-CODE-01 — 독립 통합 코드 검토

**판정: 수정 필요. 최종 인수/통과 아님.** 기존 독립 반례 13개와 전체 595개 회귀는 통과했지만 새 P1 1건·P2 1건을 재현했다. R10–11/17의 전체 판단→5단계 브리핑 연결도 잔여 범위다. 아래 결과는 지정된 고정 SHA에 대한 직접 검토이며 총괄의 통과 보고를 대신 인용한 것이 아니다.

## 기준과 격리

- 리뷰 task: `01a0e30c-b115-7db0-9a6c-b05a962b2d8c`.
- 직접 checkout한 통합 SHA: `a1a41b03594e6fa2a9ad141d7029b6f05cb53855` (runtime checkpoint `231bd6f`).
- worktree: `C:/Users/lsn/.codex/worktrees/89b8/lsn-asset-mng-skills/workspace/review-a1a41b0`.
- 기존 89b8의 b1f4514 리뷰 미추적 파일을 그대로 보존하기 위해 새 detached worktree를 만들었다. 원 worktree의 기록을 삭제하거나 덮어쓰지 않았다.
- 요구사항 `REQ-2026-09-23-v1` R01–R17, `DESIGN-2026-09-23-v0.1`, D17/D18, 최신 tasks/handoff 및 이전 세 리뷰를 기준으로 변경과 실행 경계를 검토했다. 이전 검토를 이번 SHA 실행의 대체 증거로 삼지 않았다.
- 구현·기존 테스트·공유 tasks 편집, commit/push, 배포, 자동 주문 없음. 개인 상태 검증은 임시 합성 DB만 사용. 공개 시세 직접 검증은 명시적으로 빈 credential provider를 사용했다.
- 새 독립 최종 VERIFY 세션은 이 작업과 별개이며 아직 이 보고서의 통과 근거가 아니다.

## 열린 발견 사항

### RC10-R1 [P1] 보고서 갱신이 하위 PARTIAL과 부족 입력을 잃음

- 소유 C. R14/R17, 부분 결과·불확실성 유지 계약.
- 위치: `runtime/investment_stack/execution/portfolio_thesis_modes.py:134`, `:152–161`, `:515`; `runtime/investment_stack/reporting/thesis_refresh.py:284`, `:416`.
- `rerun_fixed_mode`는 하위 ModeResult의 PARTIAL을 허용하지만 반환하는 ReportSnapshot에는 availability/missing_inputs가 없다. read_report_snapshot도 manifest 상태를 전달하지 않는다. refresh_report는 섹션 fingerprint 비교가 수행됐다는 이유로 COMPLETED를 반환하고 외부 모드는 COMPLETE가 된다.
- 재현: 기존과 갱신 포트폴리오 양쪽에 동일한 필수 callback 누락을 둔다. 12:00 UTC/state 7/snapshot 7에서 13:00 UTC/state 8/snapshot 8로 갱신한다. 자료/누락 섹션 집합이 같아 UNKNOWN delta가 발생하지 않는 입력이다.
- 실제 결과:

| 단계 | 상태 | 부족 입력 |
|---|---|---|
| 기존 PERSONAL_PORTFOLIO_ANALYSIS | PARTIAL | approved_materiality_selector, selected_assets_for_deep_research |
| 새 run의 PERSONAL_PORTFOLIO_ANALYSIS replay | PARTIAL | 같은 두 필수 입력; step 기록과 replay manifest로 확인 |
| 외부 REPORT_REFRESH | COMPLETE | 빈 배열 |
| 외부 사용자 보고서/manifest | AVAILABLE, 높은 신뢰도 | 누락 정보 없음으로 표현 |

- 본문에는 `보고서 상태: 확인 완료`, `정보 신뢰도: 높음`, `저장된 자료에서 오래되거나 서로 충돌하는 값, 제공자 누락을 확인하지 못했습니다.`가 나온다. 하위 보고서의 실제 미완료가 사용자 결과에서 사라진다.
- 기존 RC10 수정은 동일 pipeline 안의 step 누락을 전달하여 원 반례는 통과했다. 이번 반례는 재실행 결과→snapshot→갱신 결과 경계를 통과하면서 다시 누락이 소실되는 경우다. 섹션 집합이 다른 기존 E2E의 우연한 PARTIAL로는 검출되지 않았다.
- 기대: 실제 replay 보고서의 availability·누락·unknown을 외부 delta 보고서에 유지한다. 외부 runner도 같은 계약을 따라야 하며, 상태가 확인되지 않는 기존 snapshot을 임의 완료로 간주하지 않는다. 상태만 낮추고 구체 누락 이유를 숨기는 수정은 충분하지 않다.
- 독립 probe: `review_code_01_final_probes.py::test_rc10_r1_refresh_preserves_partial_replay_status`, FAIL. production dispatcher·configured composition·실제 portfolio/replay/report/run.db 서비스 사용, 외부 시세만 합성.

### RC11 [P2] 기관별 연속성 검증이 정상 기관 간 합의 집계를 차단함

- 소유 C. R13의 기관 간 방향 일치도.
- 위치: `runtime/investment_stack/institutional/scoring.py:149`, `:179–180`.
- calculate_consensus_direction가 전체 manager_comparisons를 `_valid_comparison_chain`에 전달한다. helper는 manager_cik가 둘 이상이면 False를 반환하여 기관 간 합의 집계의 정상 입력을 차단한다. RC05 기간 연속성 수정 과정에 추가된 회귀다.
- 재현: 동일 CUSIP, 동일 인접 분기 2024-03-31→2024-06-30, 기관 A/B의 서로 다른 filing, 양쪽 모두 100→200주 증가, COMPLETE/SH/NONE이고 비교 가능인 두 기록. 한 기관만 넣으면 방향 `1`, 두 기관을 넣으면 `None`.
- 기대: 각 기관 내부의 순서/연속성/중복을 먼저 검증하고 비교기간/범위가 일치하는 기관 간 방향을 집계한다. 동일 기관 중복 가산, 서로 다른 기간을 하나의 기관 간 합의처럼 합산하는 우회는 유지하지 않는다. 가중치/매매 gate는 계속 UNVALIDATED/DISABLED로 둔다.
- 독립 probe: `review_code_01_final_probes.py::test_rc11_cross_manager_consensus_accepts_two_valid_increases`, FAIL. 정책 숫자나 매매 신호를 새로 요구한 것이 아니라 기존 방향 집계의 정상 입력 회귀다.

실행 가능한 새 probe 및 stdout/stderr는 같은 폴더의 `review_code_01_final_probes.py`, `review_code_01_final_probes_output.txt`에 보존했다. 각 JSON에 기준 SHA, RC10-R1 단계별 상태/누락, RC11 1기관/2기관 결과를 기록했다. 두 발견은 재현 직후 총괄에게 회송했다.

## 직접 실행 결과

Windows Python 3.14.6, interpreter `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`. 소스 실행에는 `PYTHONPATH=runtime`을 설정하고 cwd를 새 고정 worktree로 지정했다.

| 실행 | 결과 |
|---|---|
| 현재 SHA `python -m build --no-isolation` | wheel/sdist 재빌드 성공 |
| `python -m unittest discover -s tests -q` | **595 tests OK, skipped=1**, 76.290초 |
| 첫 패스 독립 probe | **5/5 PASS** |
| 979cc5e 추가 독립 probe | **3/3 PASS** |
| b1f4514 추가 독립 probe | **5/5 PASS**, 6.584초 |
| 새 final probe | **3 tests: configured 7모드 PASS, RC10-R1/RC11 FAIL**, 7.593초 |
| 깨끗한 임시 venv에 현 wheel 설치 후 R15 | **11/11 PASS, skip0**, 0.928초; pip check 성공 |
| 현 sdist를 임시 폴더에 풀어 wheel/sdist 재빌드 | 성공 |
| 풀린 sdist 자체의 두 R15 파일 실행 | **11 OK, skip1**, 0.775초 |
| 기본 공개 HTTP executor→Phase4→Phase5 직접 실행 | Yahoo/Naver 모두 아래 결과 확인 |
| `git diff --check b1f4514 HEAD` | 성공 |

원본 및 풀린 sdist의 skip은 해당 기존 interpreter에 wheel의 sys.prefix skill tree가 없기 때문이다. 실제 clean wheel venv에서는 동일 검사가 실행되어 통과했다. 새 venv는 system-site-packages 없이 만들고 PYTHONPATH를 제거했으며 import한 investment_stack 파일이 임시 venv의 Lib/site-packages 아래임을 assertion으로 확인했다. 인터넷 설치 대신 로컬 tzdata 2026.4·truststore 0.10.4 패키지와 distribution metadata만 복사하고 wheel을 `--no-index --no-deps`로 설치했다. 테스트의 scripts import를 위한 저장소 root 추가는 runtime 소스 경로 추가와 구별된다. Python 3.11–3.13 또는 네트워크 dependency resolution 검증은 아니다.

R15의 정확한 wheel/sdist 경로 allowlist, 8개 스킬·원본/미러/UI 파일, 5개 config, ARCHITECTURE.md 포함과 source-only version 검증을 확인했다. 임의 venv의 Codex UI 자동 검색 또는 허용된 소스 텍스트 내부의 모든 비밀값 탐지까지 증명하는 검사가 아니다.

## 실제 주말 종가와 Phase5 전달

이 SHA의 `build_default_provider_executor(credentials=EnvironmentCredentials({}))`, 기본 HTTP transport, 실제 Phase4 evidence 저장, LiveDeepResearchRuntime 및 원래 Phase5 analyze_equity를 호출했다. wrapper는 Phase5에 전달한 current_price만 관찰했으며 계산 호출을 대체하지 않았다. 임시 run.db/state 0/NONE:REVIEW, 고정 cutoff `2026-09-27T12:00:00+00:00` 사용. 테스트용 재무 빈 응답은 시세 live 확인과 구별된다.

| 종목/원문 | 선택 가격·세션 | 공개가능시각 해석 | Phase5/보고 고지 |
|---|---|---|---|
| [Yahoo AAPL](https://query1.finance.yahoo.com/v8/finance/chart/AAPL) | USD 341.07, LAST_VALID_CLOSE, 2026-09-25 | 2026-09-25T20:00:01+00:00 | current_price=341.07, 비실시간 고지 True |
| [Naver 005930](https://m.stock.naver.com/api/stock/005930/basic) | KRW 286500, LAST_VALID_CLOSE, 2026-09-23 | 2026-09-23T07:30:00+00:00 | current_price=286500, 비실시간 고지 True |

두 valuation 결과는 PARTIAL이다. 이것을 전체 재무/적정가 live 분석 성공으로 확대하지 않는다. Yahoo public_available_time은 regularMarketTime을 쓰는 parser 해석이며 별도 출판시각 필드의 독립 검증이 아니다. Naver는 closePriceSendTime을 이용한 파생 시각이다. NASDAQ 9/24–28, KRX 9/22–28 pinned coverage만 확인 범위이며, 이후 일반 주말·휴장 전체를 지원한다고 주장하지 않는다. 이번에 공식 달력 원문을 다시 조사하지 않았고 앞선 검토의 출처/일정 완전성 한계를 유지한다.

## 7모드 configured composition과 안전 경계

새 독립 probe는 RuntimeServices 전체 mock 대신 실제 equity/portfolio/thesis/ledger 번들을 같은 run_db 인스턴스에 조립했다. 합성 web financial 응답과 명시적인 임시 personal ledger를 주입했다. SINGLE_ASSET_ANALYSIS와 ASSET_COMPARISON은 실제 Phase4→Phase5→Phase6를 실행했고, portfolio/scenario/thesis는 실제 typed 계산·저장을 실행했다. REPORT_REFRESH는 주입된 고정 외부 runner를 통해 실제 SINGLE_ASSET_ANALYSIS를 새 run의 시각/state/snapshot/ref와 refresh flag로 재실행했다.

- 7개 모두 고정 계획의 결과/보고서 또는 게시 영수증까지 실행됨.
- ASSET_UPDATE의 명시적으로 확정된 합성 입금만 POSTED, state version 증가.
- 다른 6개는 mutation_receipt 없음, 임시 ledger state version 불변.
- 모든 분석 보고서 반환 참조가 저장 manifest로 조회됨.
- 실제 equity refresh의 새로운 context 전달을 확인. 기존 exact-pin/flag 거부 회귀도 전체 suite에서 통과.
- 새 probe는 외부 equity runner까지 host가 명시적으로 구성했다. 기본 CLI의 빈 RuntimeServices가 자동으로 전체 공급자·개인 DB·정책을 조립한다는 뜻이 아니다.
- portfolio materiality/selected deep research가 미설정인 경우 PARTIAL인 것이 정상이며, RC10-R1이 그 상태의 갱신 전달을 손상시킨다.

## R01–R17 추적과 잔여 범위

| 요구사항 | 직접 확인한 근거 / 판정 한계 |
|---|---|
| R01 현재가 | delayed/calendar/price binding/weekend E2E 회귀 및 현 SHA live 2종목→Phase5 통과. pinned calendar 밖 일반화 없음 |
| R02 재무 기간 | selected fact/metric context/회계 기준 회귀, RC04 원·추가 반례 PASS. source metadata가 누락된 지표는 비교에서 제외 |
| R03 단위·통화 | Decimal/scale/차원 회귀, 동일 경제 상태 FX 위험 독립 반례 PASS |
| R04 SEC facts | companyfacts·공개시점·Decimal evidence·tag 회귀 통과. 이번 단계 SEC 전체 원문 live 재수집이나 모든 tag 감사는 미실행 |
| R05 fallback | 부적격·부분 응답·후속 공급자 선택 회귀 통과. 실제 2종목 기본 executor 경로와 빈 credential 처리 확인 |
| R06 웹 시세 | 원문 파서/검색 요약 우회 차단 회귀와 Yahoo/Naver 직접 확인. 다른 시장/Investing 접근을 이번 결과로 대체하지 않음 |
| R07 OHLCV | 중복·순서·OHLC·미완성/조정/출처 회귀 통과. 실제 corporate-action receipt 진위·모든 거래일 coverage 검증 완료 아님 |
| R08 차트 | 순수 지표/적격 데이터 경계/신호 gate 회귀. 기술지표의 configured 분석→최종 5단계 브리핑 연결은 잔여 범위; 미승인 신호 비활성 |
| R09 가치평가 | 모델·가정·DCF·선택 입력 및 비교 회귀. live 시세를 소비해도 재무/가정 부재는 PARTIAL이며 모든 자산 모델 live 성공 아님 |
| R10 신규매수 | action/typed briefing 검증 통과, 정책 provenance registry 부재로 WAIT/수량 없음. 기본 equity 보고서에 5단계 WAIT 브리핑이 연결되지 않음 |
| R11 추가/축소 | 순수 예산/현금·집중·FX·비게시/portfolio risk 회귀. 실제 개인 DB 사용 없음; 승인 정책 없이 수량을 활성화하지 않음 |
| R12 13F | 공시/정정/수량/기간 비교 회귀, RC05 미래·역순·gap·중복 반례 PASS. 이번 단계 실제 SEC archive 전체 수집은 미검증 |
| R13 점수 | UNVALIDATED/DISABLED gate 유지. RC11 기관 간 방향 집계 회귀 열림. 기간 외/성과·비용 검증 완료 아님 |
| R14 7모드 | 새 독립 configured 7모드 실행과 기존 pin/receipt/비게시 회귀 통과. RC10-R1 갱신 상태 전파 열림. 기본 host 자동구성 없음 |
| R15 설치/배포 | 현 wheel·clean venv·unpacked sdist 재빌드/자체검증 통과. Python 범위/UI 자동발견 한계 유지. 별도 문서 후속 diff는 아직 미수신 |
| R16 통합 | 현 SHA 595 및 13개 기존 반례 직접 실행, 새 2실패. 모든 요구사항 전체 완주와 별도 최종 VERIFY 완료가 아님 |
| R17 보고 | 기존 RC10 PARTIAL 정합성 반례 PASS이나 refresh RC10-R1 열림. 일부 한국어 개선과 긴 숫자 정리는 확인; 5단계 본문/상세근거 분리는 미완 |

R10–11/17 잔여 범위는 새 회귀와 구별한다. `execution/analysis_modes.py:424–426`은 fundamental/valuation 섹션을 `InvestmentReportBuilder.build`에 전달하지만 `briefing=NonPostingBriefing` 경로를 사용하지 않는다. execution/deep_research에는 기술지표·13F→해당 5단계 브리핑 연결도 없다. 현재 결과는 일반 분석 섹션 보고서다. C의 WAIT 안전 gate를 해제할 이유는 없으며 미승인 정책과 부족 자료를 명시한 대기 브리핑 연결이 필요하다. 모든 R10–11 요구를 충족했다고 문서화해서는 안 된다.

포트폴리오/논지 본문은 snapshot/claim ID와 과도한 소수 표시를 일부 정리했으나 보고서 제목, refresh의 CHANGED/section ID 등과 계산 ID가 본문에 남는다. `상세 계산 근거`라는 라벨 변경만으로 별도 상세 근거 구역이 생기지는 않는다. R17 전체 가독성 기준 충족 판정은 하지 않는다.

## 후속 검토 조건

1. C RC10-R1·RC11 수정과 같은 두 독립 반례 PASS. 갱신에서 구체 누락/unknown 보존 및 기관별 중복/기간 범위 음성 경계도 함께 확인.
2. B의 문서 전용 후속 SHA를 받으면 README/IMPLEMENTATION_STATUS diff를 현재 지원 범위와 재대조.
3. R10–11/17 등 미완료 제품 연결과 미확정 정책/외부 권한을 분명히 남긴 최종 통합 SHA 고정.
4. 해당 SHA에서 새 변경과 관련 회귀를 다시 검토한 뒤 검토자와 다른 새 Codex 세션이 VERIFY 수행.

이 보고서 파일 작성은 REVIEW-CODE-01의 전체 통과 또는 사용자 프로젝트 완료를 의미하지 않는다.
