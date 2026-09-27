# REVIEW-CODE-01 첫 패스 — 57aca43

- 독립 검토 task: `01a0e30c-b115-7db0-9a6c-b05a962b2d8c`.
- 직접 확인한 HEAD: `57aca433d62161ad537eaabae8ca1cd31c935d73`.
- 기준: REQ-2026-09-23-v1 R01–R17, DESIGN-2026-09-23-v0.1 및 decisions D17/D18, 최신 tasks/handoffs.
- 구현 소스 수정·commit·push 없음. 검토 문서/재현 코드만 추가. 실제 개인 DB·인증정보·주문 사용 없음.
- **첫 패스이며 인수/전체 완료 판정이 아니다.** A의 진행 중 R01 수직 실행기와 네 모드 dispatcher 연결은 이 SHA에 없음을 알고 검토했다. 후속 최종 SHA를 같은 독립 세션에서 직접 확인해야 한다. 별도 최종 검증 세션을 대신하지 않는다.

## 재현된 수정 필요 사항

### RC01 [P1] 평가통화와 다른 포지션 금액으로 위험 가중치를 계산함

- R03, R11, R14, R16. 담당 C.
- 위치: `runtime/investment_stack/reporting/portfolio_modes.py:478`, 호출 `:538`.
- `_analyze`는 FX로 환산한 총자산을 계산하지만 `_risk_result`에 원래 `request.positions`를 전달한다. 분자는 현지통화 금액, 분모는 평가통화 총자산이 되어 차원이 다르다.
- 재현: 기존 complete fixture의 USD 800 포지션을 JPY 80,000, 적격 JPY/USD=0.01로만 바꾼다. 다른 USD 200 포지션과 USD 100 현금, 평가통화 가격 series는 동일하다.
- 실제: 양쪽 총자산 1,100. 변동성은 `0.06833869382865346172156841967888632` 대 `6.586293666462636484312642572911874`. 둘 다 AVAILABLE. 승인 위험 한도 0.5의 판정까지 WITHIN에서 BREACHED로 달라진다.
- 기대: 동일 경제 상태의 allocation·risk·한도가 일치해야 한다. 시나리오 after도 그 상태의 FX 환산 금액으로 가중치를 계산해야 한다.

### RC02 [P1] Yahoo 명시 지연이 장중 FRESH 적격성으로 우회됨

- R01, R05, R06. 담당 B/A 연결.
- 위치: `runtime/investment_stack/providers/market_quotes.py:807`, evaluator `:88`.
- 파서가 `exchangeDataDelayedBy=15`를 보존해도 quote_kind는 항상 REGULAR이다. evaluator/engine의 장중 경로는 delay_minutes를 확인하지 않고 기본 20분 age 창으로 FRESH를 반환한다. 승인된 지연 정책이 없는 상태에서 선택 및 fallback 종료가 일어난다.
- 재현: NASDAQ AAPL, 2026-09-28 09:46 ET 시세, cutoff 10:01 ET, source delay 15분, pinned NASDAQ calendar. evaluator `(True, 'age=900s')`; `MarketQuoteProvider.fetch_current` 결과 AVAILABLE/Yahoo selected.
- 기대: 명시된 지연을 먼저 평가하고 별도 승인 정책 없으면 현재가 계산 부적격으로 기록하여 후속 후보를 시도한다. 정규장 종가의 LAST_VALID_CLOSE 허용과 장중 지연 승인 여부는 분리한다.

### RC03 [P1] 게시 후 projection 예외와 오류 기록 실패가 겹치면 영수증을 잃음

- R14, R16. 담당 A.
- 위치: `runtime/investment_stack/execution/dispatcher.py:137` (동일 미보호 logging 패턴 `:109`).
- 정상 result logging은 try/except로 보호하지만 handler 예외 경로의 `_record_state`는 보호하지 않는다. 이미 mutation_receipt를 확보한 뒤 projection이 실패하고 run DB 기록도 실패하면 ModeResult 대신 예외가 호출자에게 전파된다.
- 재현: DECIDE_POSTING이 POSTED/transaction_ids/state_version=7 반환 → PROJECT_PERSONAL_STATE handler가 ValueError → 그 오류를 쓰는 logger가 OSError. 실제 OSError 탈출, FAILED result/POSTED receipt 반환 없음.
- 기대: run-local logging 실패에도 이미 확정한 receipt가 포함된 FAILED 결과를 반환하고 복합 후속 분석을 중단한다. 이 반례는 합성 handler/logger 경계 테스트이며 실제 DB 디스크 장애를 주입한 실험은 아니다. 기존 실제 합성 personal DB 게시/재시도와 단일 projection 실패 검증은 회귀 suite에서 통과했다.

### RC04 [P1] 종료일만 같은 연간/분기·회계기준을 비교 가능으로 확정함

- R02, R09, R14, R17. 담당 A.
- 위치: `runtime/investment_stack/execution/analysis_modes.py:148` (기간 추출 `:129`, 비교값 생성 `:183`).
- compatibility matrix는 period_end 집합·통화·business type만 확인하고 start/duration/frequency/accounting/consolidation/adjustment basis를 무시한다.
- 재현: 기존 실제 두 자산 모드 integration fixture의 fundamentals metadata만 변경. FANUC는 start=2025-07-01/ANNUAL/US-GAAP, KEYENCE는 start=2026-04-01/QUARTER/IFRS, 둘 다 end=2026-06-30·JPY·CONSOLIDATED·REPORTED. Phase4→5→비교→run.db 보고까지 실행.
- 실제: period_compatible=True, compatible=True, matrix.complete=True; 매출/EPS 및 valuation.pe, ev_to_ebitda 등의 값·차이 13개 저장/보고. 전체 모드가 다른 누락 때문에 PARTIAL이어도 잘못된 비교 가능 판정과 수치는 노출된다.
- 기대: 실제 선택 financial evidence의 전체 기간/회계 basis를 대조하고 불일치/누락이면 해당 지표 비교값 및 delta를 차단한다.

### RC05 [P1] 13F feature가 미래 기간을 point-in-time으로 표시함

- R12, R13, R16. 담당 C.
- 위치: `runtime/investment_stack/institutional/scoring.py:42`, `:124`; 관련 `institutional/compare.py:62`.
- `compute_institutional_features`는 aware as_of 여부만 확인하고 비교 기록의 기간/공개시점을 대조하지 않은 채 is_point_in_time=True를 반환한다. 비교 DTO에는 검증된 공개시점 자체가 없어 과거 종료일만 검사해도 충분하지 않다.
- 재현: 같은 기관·CUSIP의 2026-06-30 100주 → 2026-09-30 200주 비교를 as_of=2026-09-27에 공급한다. 실제 holding_period=9/30, 증가율 1, 방향 +1, 품질 1.0, is_point_in_time=True. 반대로 compare_portfolios(9/30, 6/30)도 comparable=True/DECREASED로 반환한다.
- 기대: 기간 순서·연속성 및 두 공시 버전의 공개가능시각을 검증할 수 없으면 PIT 미확인/feature 차단. 미래 데이터가 단지 UNVALIDATED라는 표식 아래 당시 공개 정보처럼 남아서는 안 된다.
- 한계: 매매 gate는 여전히 DISABLED/UNVALIDATED라 이 반례가 자동 매매 또는 확정 매수 신호를 만든다고 주장하지 않는다. 실제 SEC 원문 수집부터 이어진 공격 재현은 아니다.

## 직접 실행한 검증

공통 인터프리터: `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`. `PYTHONPATH=runtime`으로 이 worktree 소스를 사용했고 traceback 경로도 확인했다.

1. `python -m unittest discover -s tests -q`: **558 tests, 1 FAIL, 1 skipped**. 실패는 fresh checkout에 dist가 없는 `tests/test_packaging.py:55`의 빌드 전제였다. 런타임 테스트 실패로 오인하지 않는다.
2. `python -m build --no-isolation`: wheel/sdist 생성 성공. 선언된 설치 환경에 있던 build/setuptools 사용, 신규 다운로드 없음.
3. `python -m unittest tests.test_packaging -q`: **5 tests, OK, 1 skipped**.
4. `python scripts/sync_agent_skills.py --check`: exit 0. `git diff --check`: exit 0.
5. `python docs/workflow/reviews/review_code_01_first_pass_probes.py -v`: **5 tests, 5 FAIL**. RC01–05의 안전한 기대값을 assert하는 회귀 코드이므로 baseline에서 실패한다. 구현 테스트 디렉터리에 넣지 않았으며 원 소스 수정 없음.
6. 빌드 후 전체 suite 재실행은 아래 후속 실행 결과에 기록한다.

## 주말 종가와 live/fixture 구분

- 2026-09-27 이 세션이 기본 `providers.http.fetch_json`을 통해 공개 Yahoo AAPL chart API와 Naver 005930 basic API를 직접 조회하고 파싱했다. 둘 다 JSON 조회 성공. 테스트에만 적힌 숫자를 live 확인으로 승격하지 않았다.
- Yahoo: USD `341.07`, `regularMarketTime` → 2026-09-25 16:00:01 ET, delay field 없음. parser는 같은 시각을 public_available_at으로 지정한다. 이는 parser의 source-time 해석이며 별도 출판시각 필드를 확인한 것은 아니다.
- Naver: KRW `286500`, 파생 정규장 종가시각 2026-09-23 15:30 KST, `closePriceSendTime`에서 16:30 KST 공개가능시각, delay 0. 원 장후 체결시각과 정규장 종가를 분리하는 기존 fixture/코드도 대조했다.
- cutoff=2026-09-27T12:00:00Z, pinned calendar로 두 값 모두 LAST_VALID_CLOSE 경로 적격. NASDAQ 9/24–28 및 KRX 9/22–28 밖은 coverage 없음. 임의 일정·중간 세션 누락·과거 세션·개장 중 미완성 bar 차단 회귀 포함.
- [Nasdaq 2026 휴장표](https://nasdaqtrader.com/Trader.aspx?id=Calendar), [9/25 corporate action 공고](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-685), [행안부 추석 공지](https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=129490), [KRX 안내 페이지](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp), [TRN](https://trn.krx.co.kr/index.jsp)를 독립 열람했다. Nasdaq 공고는 IPEX 등의 9/25 마지막 거래일을 기술한 corporate action이며 전체 종목 세션 완전성 영수증은 아니다. TRN은 파생 모의거래 서비스다. KRX 안내의 web 텍스트는 wrapper 수준이므로 세부 규칙 재확인을 완료했다고 하지 않는다. 이 자료만으로 일반화된 전년도/전년도 이후 rolling calendar를 검증하지 않았다.
- 이 SHA의 ProviderFallbackExecutor/default provider/현재가 소비 경계까지 LAST_VALID_CLOSE 연결은 미완이다. tasks와 B handoff가 이미 명시하고 A가 수정 중이므로 새 결함으로 중복 계산하지 않았다.

## R01–R17 첫 패스 coverage와 남은 검토

| 요구사항 | 직접 확인/이번 판단 |
|---|---|
| R01/05/06 | calendar·quote·executor 코드와 회귀/live 2원천 확인, RC02. 잘못된 웹 현재가의 최종 우회 차단은 A 후속 SHA에서 재검토 필수 |
| R02/03 | selected 재무 관련 회귀 실행, 실제 comparison 반례 RC04, FX 차원 오류 RC01 |
| R04 | SEC CompanyFacts/Decimal/공개시점 기존 회귀 실행. 이번 세션 SEC live 원문 재수집 및 모든 tag별 별도 감사는 미실행 |
| R07/08 | OHLCV·technical 기존 회귀 실행. 실제 corporate-action/calendar receipt 진위, 신호 정책 승인, 보고서 끝까지 연결은 별도 미검증 |
| R09 | valuation/explicit DCF 기존 회귀 실행. RC04의 기간 다른 배수 비교 차단 필요; 모든 모델별 live 입력 검증은 미실행 |
| R10/11/17 | action/briefing/typed binding 회귀 실행. 위험 규모 입력에 RC01, 비교 본문에 RC04 영향. 미승인 정책 WAIT와 임의 주문 금지 경계 유지 |
| R12/13 | parser/비교/validation/scoring 회귀·소스 확인, RC05. 독립 point-in-time 실증/기간 외 검증 완료 아님, 가중치 gate 비활성 유지 |
| R14 | 실제 두 분석 bundle·asset update·C pure services 회귀 확인. RC03/04; 네 모드 dispatcher와 state loader의 최종 통합은 후속 SHA 대상 |
| R15 | 현 source/mirror 동기화·빌드 산출물 검사. README의 fresh install→unittest 절차에는 build 전제가 누락되어 깨끗한 환경에서 1 FAIL 재현. README와 IMPLEMENTATION_STATUS는 후속 기능을 반영하지 못한 설명도 있어 최종 갱신 필요 |
| R16 | 이 SHA 직접 suite 및 추가 반례 실행. 전체 요구사항 완주·모든 live provider 성공·다른 새 최종 검증 완료를 선언하지 않음 |

## 후속 실행 결과

빌드 후 같은 인터프리터/PYTHONPATH로 `python -m unittest discover -s tests -q` 재실행: **558 tests in 49.719s, OK (skipped=1)**. 기존 suite 통과와 별도 독립 반례 5 FAIL은 함께 읽어야 한다. 최종 통합 SHA 리뷰는 아직 시작하지 않았다.
