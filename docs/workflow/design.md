# 투자 분석 보완 구현 명세 초안

버전: **DESIGN-2026-09-23-v0.1** · 상태: **초안, 구현 계약 승인 전**

- 작업: DESIGN-01. 요구사항: REQ-2026-09-23-v1, R01–R17.
- 코드 기준: `3d4a95ba33d582f67a99de7b410b160e62645961`.
- 작성일: 2026-09-23. 근거: 현재 코드·지정 로컬 자료. 외부 서비스 접속·시장 자료 수집은 하지 않았다.
- 이 문서의 타입·함수·경로 중 **제안**으로 표시한 것은 아직 구현되어 있지 않다. 설계상 필수 조건도 구현 완료를 뜻하지 않는다.
- 이번 복구 세션은 원본 작업 폴더에서 문서별 단일 작성자로 분리했다. 편집은 design.md, decisions.md, handoffs/DESIGN-01.md만 한다. requirements/tasks/AGENTS/baseline은 총괄 소유다.

## 1. 유지할 경계와 현재 공백

8개 스킬, 7개 요청 모드, 모드별 고정 파이프라인, Python의 결정론적 계산, personal.db/run.db 분리를 유지한다. 차트와 13F는 우선 기존 자산 분석 내부의 typed runtime 구성요소로 제안한다. 새 스킬·모드·DB·범용 DAG는 도입하지 않는다. 구조 확정 및 예외는 decisions.md에서 별도 검토한다.

현재 소스 확인 결과는 다음과 같다. 총괄의 합성 재현 결과는 baseline.md를 참조하며, 이 세션에서 새로 실행한 결과와 혼동하지 않는다.

| 현재 위치 | 확인한 구현/공백 | 설계 대응 |
|---|---|---|
| `deep_research.py::_current_price` | UNKNOWN/UNAVAILABLE만 제외해 STALE을 통과시킴 | R01, 목적별 공통 적격성 |
| `deep_research.py::_normalize_financials` | provider_results를 다시 순회; 시각·등급으로 지표 선택, 기간 묶음 미검증 | R02–03, selected fact set만 계산 |
| `_explicit_scale`, `_unit_scale` | 잘못된 명시 배율과 미지정이 같은 None; 기본 1로 복귀 | R03, 미지정/오류의 별도 상태 |
| `providers/adapters.py::SecCompanyFactsAdapter` | 중첩 facts를 단일 관측으로 반환 | R04, fact별 변환 |
| `providers/execution.py::execute` | `result.usable`이면 중단; usable은 관측 존재/전송 상태 기준 | R05, 요청 충족 검사 후 종료 |
| `evidence/research.py` | selected rows와 deep_research의 재선택이 별개; 선택 키에 기간 시작/길이 없음 | 공통 selector, 실제 입력 계보 |
| `freshness/engine.py` | 여러 시각 중 최초를 사용; CLOSED/HOLIDAY와 날짜 존재만으로 종가 인정 | 공개시점과 관측시점 분리, 세션 검증 |
| `web_research/adapter.py`, `bundle.py` | 주입된 hit 검증 경계; 시장별 실제 페이지 조회 성공 증거가 아님 | R06, 실제 수집 어댑터 계약 |
| `calculations/valuation.py`, `deep_research.py` | 명시 DCF 타입은 있음; live bridge는 DCF 가정을 전달하지 않음 | R09, 모델 가정 입력 연결 |
| `asset_analysis.py::_persist_result` | 입력에 subject/evidence 묶음을 기록; 숫자별 입력·변환 재현 계약 부족 | 계산 입력 binding 기록 |
| `routing/router.py`, `cli.py`, `pipelines/planner.py` | 키워드 라우팅, route/plan/check, 단계 목록; 7개 실행 완주와 다름 | R14, 고정 dispatcher와 결과물 |
| `tests/acceptance/test_phase8_request_modes.py` | 라우트·계획·non-posting 단계 경계 검사 | 실제 모드별 실행 acceptance 추가 |
| runtime/tests/config/skills 검색 및 총괄 확인 | OHLCV·RSI·MACD·13F 전용 구현 확인 안 됨 | R07–08, R12–13 신규 내부 모듈 |
| README/pyproject/sync 스크립트 | Windows tzdata 선언과 안내 불일치; SKILL.md만 미러 복사 | R15, 설치·배포 검증 |

## 2. 공통 계약 C01–C07

### C01 — 실행 컨텍스트와 공개시점

`RunContext` 제안: run_id, request_mode, analysis_as_of(시간대 포함), analysis_timezone(IANA), runtime_version, config_version, contract_version, source_manifest_hash, optional pinned_personal_state. 개인 상태는 db_instance_id/state_version/portfolio_data_as_of를 함께 고정한다. 개인 상태가 필요 없는 단일 분석에는 `NOT_APPLICABLE`을 쓰며 가짜 개인 DB를 생성하지 않는다.

시간은 의미를 분리한다.

- observed_at/period_end: 시장 관측/재무 대상 시점.
- public_available_at: 그 **버전**이 공개되어 사용할 수 있었던 시점. 발표·제출의 정확한 시각과 근거 locator를 저장한다.
- retrieved_at: 이번 조회시각. 앞의 두 시각을 대체하지 않는다.
- superseded_at: 정정 등 다음 버전 공개시점. 원 fact를 덮어쓰지 않는다.
- date-only 자료는 `availability_precision=DATE`, source_timezone, 가능한 공개시각 구간을 보존한다. 정확한 acceptance 시각을 확인하면 이를 사용한다. 날짜밖에 없으면 구간 상한 이전 cutoff에서 사용하지 않는다. 상한은 보수적 적격성 경계일 뿐 실제 공개시각으로 표시하지 않는다. 시간대도 모르면 공개시점 확인 불가다.

적격 조건은 관측/대상 종료시점과 공개시점이 모두 cutoff 이하여야 한다. 과거 기간 자료라도 나중 정정된 버전을 이전 cutoff에 넣지 않는다. 실제로 미래를 대상으로 한 경영진 guidance는 `FORECAST`로 분리하고, 발표시점은 cutoff 이하이어야 한다. 이를 미래 actual fact로 사용하지 않는다. 과거 검증에서 현재 웹페이지에 나타난 과거값만으로 당시 이용 가능성을 입증하지 않는다.

### C02 — EvidenceEnvelope와 목적별 EligibilityDecision

기존 ProviderObservation을 유지하면서 typed payload를 연결하는 호환 계층을 제안한다. 공통 envelope는 instrument identity(거래소·상장 종류·통화·기초자산 구분), evidence_id, source/provider/URL/locator, 원값·원단위, 수집/관측/공개시각, schema_version, content fingerprint, confirmation, 품질 문제를 가진다. credential/개인 원장/전체 기사 저장은 금지한다.

`evaluate_eligibility(observation, context, purpose, policy)` 제안의 결과:

| 필드 | 의미 |
|---|---|
| purpose | CURRENT_PRICE / FINANCIAL_CALC / HISTORICAL_BAR / INSTITUTIONAL_COMPARE / FX_CONVERSION 등 계산 목적 |
| eligible | 이 목적의 입력 가능 여부. 전송 성공과 별개 |
| reasons | 시간·단위·통화·종목·기간·출처·숫자·coverage 실패 코드와 짧은 설명 |
| freshness | 기존 enum 유지; 재무/13F의 보고 주기와 가격 TTL을 혼용하지 않음 |
| policy_version | 지연/종가·캘린더·모델 적용 정책 식별 |
| available_metrics / missing_metrics | 요청된 지표 계약 충족 상태 |
| input_fingerprint | 검사한 payload와 선택 결과의 동일성 확인 |

유한 Decimal만 허용한다. NaN/Infinity/bool/빈 문자열/잘못된 날짜는 개별 자료 오류로 격리하고 후속 후보를 시도한다. 자료의 `calculation_input_approved=True` 자기 선언만으로 적격성을 얻지 못한다. source tier 역시 검증된 어댑터 메타데이터에서 부여한다.

현재 가격 정책 초안:

| 상태 | 현재가 의존 계산 | 표시/추가 조건 |
|---|---|---|
| FRESH | identity, 양수·유한 가격, 통화, 실제 가격시각, 세션이 검증되면 허용 | 관측시각과 시장 상태 |
| DELAYED | 버전 있는 시장/목적 정책에서 허용한 지연 범위만 조건부 허용 | 지연 시간·실시간 아님 표시; 분 단위 허용치는 미확정 |
| LAST_VALID_CLOSE | 거래소 캘린더로 cutoff 당시 마지막 완료 세션임을 확인한 종가만 조건부 허용 | 최근 유효 종가·거래일 표시; 아무 과거 거래일을 휴장 종가로 승격 금지 |
| STALE/UNKNOWN/UNAVAILABLE/미래 | 금지 | 과거 관측 목록에 날짜와 실패 이유 보존 |

정규장·시간외·통합시세·거래소별 시세는 서로 다른 quote_kind다. 시간외 최신값이 정규장 종가를 묵시적으로 대체하지 않는다. 캘린더 미확인, 장중 거래정지 등은 자동 종가 적격 처리를 금지한다. 24/7 자산에는 증시 휴장 예외를 적용하지 않는다. 통화 없는 가격도 계산에서 제외한다. 재무 적격성이 가격 없어도 성립하면 재무 분석은 계속하되 현재 배수·비중·매매 규모 등은 unavailable이다.

### C03 — 선택은 한 번, 입력은 그 결과만

`SelectionRequest` 제안: instrument, purpose, required_metrics, target_period/basis/currency, session/quote_kind, quality policy. `SelectedInputSet`은 slot별 canonical 값·원 evidence_id·변환 calculation_id·eligibility_id와 제외 후보 이유를 반환한다.

모든 공급자 후보를 보존하고 적격성을 먼저 판정한 다음 비교 가능한 그룹만 선택한다. 재무는 목표 기간/회계/단위 일치 → cutoff 당시 적용 가능한 정정 계보 → 출처 우선순위 → 검증된 공개시점 순으로 처리한다. 정책상 동률인데 값이 충돌하면 `UNRESOLVED_CONFLICT`로 해당 slot을 막는다. 같은 값 중복은 내용 fingerprint/원본 locator로 안정적으로 정렬해 선택한다. 입력 순서·임의 UUID가 결과를 결정하면 안 된다.

원본 관측의 최신성 선정과 계산용 선정은 별개 목적을 기록할 수 있지만, 계산은 **자기 purpose의 확정 선택 세트만** 읽는다. `provider_results`를 계산부에서 다시 선택하지 않는다. 여러 수집 batch의 선택 기록을 쌓기만 해 동시에 두 현재가가 selected인 상태로 만들지 않는다. `(run, instrument, purpose, slot, selection_version)`에서 단일 승자와 supersedes 관계를 보장한다. 보완 조회 후 전체 후보 집합을 재평가하며 계산 시작 전 선택 세트를 고정한다.

### C04 — FinancialFact와 기간 묶음

`FinancialFact` 제안 필드:

| 범주 | 필드 |
|---|---|
| 식별/원본 | fact_id, evidence_id, issuer_id, taxonomy, original_tag, canonical_metric, source_locator, mapping_version |
| 수치/단위 | raw_value, raw_unit, explicit_scale 상태, normalized_value, dimension(MONEY/SHARES/MONEY_PER_SHARE/RATIO/COUNT), currency, normalization_version |
| 기간 | period_type(INSTANT/DURATION), start/end, duration_days, fiscal_year/fiscal_period, reporting_frequency(ANNUAL/QUARTER/YTD/TTM), fiscal_calendar_id |
| 기준 | consolidation, accounting_standard, adjustment_basis(REPORTED/ADJUSTED), dimensions/segment, share_basis(END/BASIC_WEIGHTED/DILUTED_WEIGHTED) |
| 버전/시각 | form, accession, filed_date, accepted_at, availability_precision, public_available_at 또는 구간, restatement_of, retrieved_at |
| 상태/계보 | supported_mapping, eligibility, derived_from, transformation_id |

기간을 알 수 없는 metadata에 임의 annual을 넣지 않는다. 동일 period_end만으로 3개월·6개월 누적을 동일시하지 않는다. 동일 회계연도 label만으로 달력 기간이 같다고 보지 않는다. 연결/별도, IFRS/US-GAAP 등 회계기준, 보고/조정, 계속사업/총사업 및 segment가 다르면 비교를 차단하거나 명시적 reconciliation을 요구한다.

`FinancialSetRequest`는 계산별 필수 지표와 기준을 정한다. 손익 비율은 동일 duration 묶음, 성장률은 동일 길이·동일 기준의 당기와 비교기, 대차대조표는 필요한 instant, ROE/ROIC는 기간에 맞는 평균 자본과 세후 영업이익을 요구한다. 평균 잔액이 없으면 기말 잔액으로 몰래 대체하지 않는다. 매출 성장의 음수/영 분모는 지표별 의미 검증 후 계산 불가 또는 절대 변화로 표시한다.

- 분기 flow: 같은 연도·기준·정정 vintage의 `YTD_n - YTD_(n-1)`; FY-Q3YTD로 Q4 도출 가능. 단조 증가 모양만으로 YTD를 추정하지 않는다.
- TTM flow: 연속된 적격 4개 분기 합 또는 검증된 FY + 현재YTD - 전년동기YTD. 겹침·구멍·53주/회계연도 변경은 정책으로 처리하며 비교 한계를 표시한다.
- stock/비율/EPS: balance 항목이나 주식 수를 4분기 합산하지 않는다. EPS는 가중평균 주식 수·희석·분할 기준을 별도 정합화한다. 기말 유통 주식 수와 diluted weighted shares를 같은 값으로 취급하지 않는다.
- 가이던스: 공시가 명시한 대상 기간으로 연결한다. 참조의 무조건 +1분기 규칙은 채택하지 않는다. 수정 guidance의 발표시점을 각각 보존한다.
- 실제 사용한 fact별 기간에서 financial_data_as_of를 만든다. 전체 수집 행의 최대 period_end로 표시하지 않는다.

### C05 — 단위·통화

명시 배율은 ABSENT/VALID/INVALID를 구분한다. 문자열 단위는 허용 문법으로 parse하며 원/천/백만/십억, 개별 주/천주/백만주, 통화/주를 dimension과 scale로 분해한다. 명시 배율이 있으면 양수·유한임을 검증한다. 단위 표현과 metadata 배율이 모두 있으면 의미상 일치 여부를 확인하고 한 번만 적용한다. 충돌하거나 의미가 불명확하면 실패한다. 단위가 없거나 알 수 없는 접미사가 있으면 magnitude로 추정하지 않는다.

`unit=USD`와 `currency=JPY` 충돌은 차단한다. 주식 수에 금액 단위, EPS에 총액 단위, 주당 수치에 총액 배율을 적용하지 않는다. 정규화 함수는 이미 정규화된 payload에 배율을 다시 곱하지 않도록 typed stage를 구분한다. FX는 원/목적 통화, 방향, rate, 기준시각, evidence/selection ID를 요구하고 flow/stock/시가 평가에 맞는 FX 기준을 선택한다. 환율의 역수·교차환율도 계산 계보를 기록한다. 변환 근거 없으면 통화별 결과를 병기한다.

### C06 — 공급자 실행과 저장

`collect(request, evaluator, ordered_candidates)` 제안은 고정 순서로 후보를 호출하고 매번 전송 결과 → schema/정규화 → 적격성 → 부족 slot을 평가한다. 종료는 필수 slot 충족과 요구 품질 달성 시점이다. 선택적 항목 부재만으로 무한 재시도하지 않는다. AVAILABLE이지만 빈 지표, stale, wrong instrument/currency, 숫자/시각 오류, 부분 재무는 다음 후보를 막지 않는다.

attempt에는 sequence, provider, capability, started/finished, outcome, accepted/rejected slot, reason, bounded retry 횟수를 기록한다. timeout/rate-limit/access denial은 정해진 예산 내 재시도하거나 다음 공급자로 간다. 예산 소진은 `BUDGET_EXHAUSTED`, 전체 후보 소진은 `CANDIDATES_EXHAUSTED`, 설정 없는 공급자는 `NOT_CONFIGURED`로 구분한다. credential 값·인증 URL은 기록하지 않는다. 적격한 기존 값을 보완 실패로 잃지 않는다. 실패한 모든 후보 수를 성공한 필수 지표의 unavailable 원인처럼 보고하지 않는다.

run.db 기존 evidence/observations/calculations/task_states/provider_states를 사용하고 typed JSON metadata를 버전 검증한다. 구체 저장 확장 초안은 §9 및 결정 D03에 따른다. 연구 경로는 개인 DB writer를 받지 않도록 의존성을 분리한다.

### C07 — 계산/주장 계보와 완료 상태

`CalculationRecord`는 formula_id/version, 실제 normalized 입력값·단위·기간·evidence_id, 선행 계산 ID, 가정 ID, 선택 ID, as_of, config hash, 결과·반올림 정책·상태·실패 이유를 갖는다. run-local 무작위 ID를 제외한 의미 결과는 재실행/입력 permutation에 불변이어야 한다. 상세 근거에서 원값 → 단위/FX/기간 변환 → 모델 → 판단 → 표시 셀을 따라갈 수 있어야 한다.

데이터 availability(AVAILABLE/PARTIAL/UNAVAILABLE), 실행 상태(COMPLETED/PARTIAL/UNSUPPORTED/FAILED/WAITING_CONFIRMATION), 투자 판단(매수/추가매수/보유/대기/축소)은 별개다. 계획 출력·원본 수집 성공·보고서 파일 존재만으로 COMPLETED가 아니다. 필수 단계의 실제 결과와 lineage 검증이 완료되어야 한다. 누락은 affected metric/section만 낮추되 그 입력을 의존하는 가격 구간·규모·판단은 함께 낮춘다.

## 3. R01–R07: 수집과 정상화

### R01–R05 구현 단위

R01은 C02를 연구 종료·deep_research·현재 배수·위험/비중·브리핑 모두에 적용한다. 계산부에서 raw Decimal을 받을 때도 검증된 binding 없이 current price라고 인정하지 않는다. 기존 스킬의 문구만 바꾸는 수정은 불충분하다.

R02–R03은 C04/C05를 먼저 적용한 뒤 FinancialSet을 만든다. 단위 불일치와 기간 불일치는 서로 다른 오류다. 일부 지표가 누락되어도 같은 기준의 나머지 지표는 사용한다. 실패를 0으로 대체하지 않는다.

R04 SEC 변환은 `facts → taxonomy → tag → units → fact[]`를 순회하는 별도 parser로 제안한다. 원본의 val/unit/start/end/fy/fp/form/accn/filed/frame 및 namespace/tag를 보존하고 namespace·tag·차원·단위가 검증된 mapping만 canonical 지표로 보낸다. 비표준 issuer tag는 자동 유사어 추정하지 않는다. USD/shares 같은 복합 단위도 처리한다. 형식별 필수 정보가 부족하면 정확한 reason을 반환한다.

accession별 제출/acceptance 메타데이터를 결합해 C01을 만족시킨다. Company Facts만으로 상세 연결/segment/정정 관계가 확정되지 않으면 공시 원문 보완이 필요하다고 표시한다. 같은 period/tag가 반복되었다고 단순 최신 filed만 채택하지 않는다. 중복과 정정을 구분하고 원래 공시와 정정의 적용 범위를 확인한다. 과거 cutoff에서는 당시 공개된 버전만 고른다. 최소 fixture는 구조를 실제 응답 형태에 맞추되 합성 숫자로 만들고, 이후 승인된 live 검증에서 실제 구조와 parser 동작을 대조한다. 조회 성공과 usable metric count를 별도 보고한다.

R05는 C06으로 첫 stale 공급자 뒤 적격 공급자, 모두 stale 뒤 웹, 부분 재무 뒤 부족 지표 보완, 모든 경로 실패를 검증한다. invalid 입력 때문에 전체 수집이 exception으로 중단되지 않아야 한다.

### R06 시장별 웹 시세 후보와 접근 검증

아래는 **검증 전 후보 순서**이며 해당 페이지/API의 현재 접근 가능성이나 사용권을 확인했다는 뜻이 아니다. 공급자 registry에는 country/exchange/quote_kind/capability/접근 상태/검증일을 포함한다. 공식 시세가 실제 필요한 필드를 제공하지 않으면 다음 후보로 이동한다.

| 시장/형태 | 구조화/공식 후보 → 웹 대체 후보 | 필수 확인 |
|---|---|---|
| 한국 상장 주식·ETF | KRX 등 공식 제공 경로 → 네이버페이증권 종목 원문 → Investing.com 종목 원문 | 정확한 종목코드·거래시장·KRW·가격시각·장 상태·지연 표시 |
| 미국 상장 주식·ETF | 거래소/승인된 timestamp 공급자 → Investing.com 종목 원문 → 추가 승인된 대체 시세 페이지 | 상장 거래소·통화·정규/시간외·quote timestamp·delay |
| 일본 상장 주식·ETF | JPX 등 공식 제공 경로 → 일본 현지 시세 원문 후보 → Investing.com 원문 | 거래소·4자리/확장 코드·JPY·Tokyo session/휴장 |
| BTC | 기존 Kraken trade 등 명시 venue/pair → 다른 승인된 venue → 동일 pair 웹 원문 | venue·base/quote·trade/quote 구분·24/7 시각 |
| 금·은 | 상품 형태에 맞는 거래소/벤치마크·발행사 → 검증된 웹 원문 | spot/futures/ETF/physical 구분, 만기·중량·순도·통화·premium |

수집기는 실제 페이지를 열어 렌더/응답의 필드를 확인하고 locator, 조회시각, 가격시각, source-kind를 structured hit으로 전달한다. 검색 요약은 URL 탐색에만 사용한다. “오늘”·상대시각은 페이지 시간대와 날짜가 확정되어야 하며 조회시각에서 가격시각을 만들지 않는다. 다른 종목 위젯·뉴스 중 가격·스크린샷 단독값은 제외한다. 접근 거부/로그인/구조 변경/필드 누락은 추적하고 승인된 대체를 시도한다. 접근제한 우회나 계정 자동 확보는 설계에 없다.

완료에는 최소 각 목표 시장의 성공 증거 또는 정확한 제한 증거, stale→대체 성공, 전 후보 실패, identity/통화/시각 오류를 포함한 fixture/live 결과의 구분이 필요하다. live 경로 미검증인 경우 R06 전체 완료를 주장하지 않는다.

### R07 OHLCV

`Bar` 제안: instrument/exchange/venue, interval, session_date, open_time/close_time, timezone, open/high/low/close/volume, currency, volume_unit, adjustment_mode(RAW/SPLIT_ADJUSTED/TOTAL_RETURN), corporate_action_version, is_complete, public_available_at, evidence_id.

finite, 가격 양수, 거래량 0 이상, `low ≤ min(open,close) ≤ max(open,close) ≤ high`, key 중복, 시간 순서, cutoff 이후·미완성 봉을 검증한다. 거래량 0과 미제공을 구분한다. 거래소 캘린더 기준 누락 세션·중복·연속성 구간을 기록하고 빈 거래일을 전일값으로 채우지 않는다. 휴장과 데이터 누락도 구분한다.

분할 조정 계수의 출처·적용일을 보존하고 OHLC 전체와 volume의 일관성을 검사한다. adjusted close만 있는 공급자에서 raw OHLC와 혼합 봉을 만들지 않는다. 수익률용 total return과 가격 수준용 split-adjusted를 구분한다. 차트 수준을 주문 가격 문맥에 표시할 때 raw/current share basis로 변환한 근거가 필요하다. 과거 검증에서 나중 corporate action을 통해 과거 신호가 바뀌지 않도록 당시 이용 가능 adjustment vintage를 고정한다.

부적격 봉이 있는 rolling window는 지표별 unavailable 처리하고 유효 연속 구간만 사용한다. `HISTORICAL_PRICE` capability 내 typed OHLCV payload로 제안하며 capability/DB 확장이 필요하면 D03에서 결정한다.

## 4. R08–R09: 차트와 적정가

### R08 계산 명세 초안

다음 공식·초기화는 테스트 가능한 계산 규약의 제안이다. 기간 n/fast/slow/signal, 매매 임계값, 적용 시장과 가중치는 미확정이다. 후보 설정을 명시하지 않은 실행은 신호를 생성하지 않는다.

| 계산 | 공식·최소 자료·경계 |
|---|---|
| SMA(n) | 적격 완료 종가 n개 합/n; n개 이전 unavailable |
| EMA(n) | alpha=2/(n+1), 첫 n개 SMA로 seed, 이후 alpha*C+(1-alpha)*prev; seed/표본시작 기록 |
| RSI(n) | 종가 차 n개로 상승/하락 평균 seed, Wilder 방식 `(prev*(n-1)+gain_or_loss)/n`; 첫 값 n+1종가. 평균손실 0·상승 양수는 100, 평균상승 0·하락 양수는 0, 둘 다 0은 50(계산 규약 제안) |
| MACD(f,s,k) | f<s; EMA(f)-EMA(s), signal은 MACD k개 SMA seed 후 EMA(k); histogram=MACD-signal. 첫 signal은 s+k-1종가 이후 |
| 상대 거래량(n) | 현재 volume / **이전** n개 완료 봉 volume 평균; 영/누락 분모 unavailable |
| 변동성(n) | n개 로그수익률의 표본표준편차, 필요 시 sqrt(시장별 연간 세션수) 적용; n+1가격, n≥2; 연율화 계수도 설정·계보 |
| ATR(n) | TR=max(H-L,abs(H-prevC),abs(L-prevC)); n개 TR 평균 seed 후 Wilder smoothing; 이전 close 필요 |

추세는 가격-SMA/EMA 관계·평균선 기울기·교차 여부의 계산 결과로 먼저 보고한다. 지지/저항 후보는 **직전** lookback 구간 고저 또는 pivot 규약으로 산출하고 사용한 봉 ID를 기록한다. pivot의 오른쪽 확인 봉이 필요하면 그 봉이 완료된 시점까지 발표를 지연한다. 미래 봉을 미리 읽지 않는다. 돌파 후보는 이전 저항 위 완료 종가와 설정된 확인 봉/volume 조건을 모두 만족할 때만 생성한다. 동일 봉으로 저항을 만들고 돌파를 동시에 선언하지 않는다.

RSI 과매도·골든크로스·13F 증가 하나로 매수를 결정하지 않는다. 공식 fixture, 일정/상승/하락 시계열, 분할/구멍/미래/짧은 표본, prefix invariance(미래 자료 추가해도 과거 결과 불변)를 검증한다. 표준 파라미터 예시도 production defaults로 임의 채택하지 않는다.

### R09 가정·시나리오·민감도

`ValuationAssumption` 제안: assumption_id, name/value/unit, kind(OFFICIAL_GUIDANCE/DERIVED/ANALYST_SCENARIO/USER), source/evidence, published/available time, applicable_period, rationale, scenario, valid_range, approval/config_version. 가정은 사실과 별도 저장하며 beta/WACC/ERP/성장률/배수/세율/순부채/희석주식 수를 기본값으로 채우지 않는다. 근거 없는 analyst 가정은 계산 불가 또는 명시적 조건부 예시로만 남긴다.

기존 business type별 모델 선택을 유지한다. 안정 현금흐름 기업은 FCFF/FCFE 종류를 명시한다. FCFF는 `EBIT*(1-tax)+D&A-capex-ΔNWC`, WACC 할인 후 `EV-net_debt-기타우선청구권+별도비영업자산`을 equity로 연결하고 net_debt에 포함된 현금을 다시 더하지 않는다. FCFE는 자본비용으로 할인하고 순부채를 다시 차감하지 않는다. 현재 OCF-capex를 FCFF라고 자동 간주하지 않는다. terminal은 g<할인율, 모든 입력 finite, shares>0, 기간/현금흐름/통화 일치를 요구한다. 비양수 equity는 해당 모델 결과와 한계를 드러내며 정상 양수 적정가로 다듬지 않는다.

금융회사는 P/B·ROE·배당, 적자·고성장은 매출/단위경제 시나리오, 복합기업은 SOTP, 자산 중심은 NAV를 쓰되 enterprise/equity/per-share 단계와 중복 항목을 명시한다. ETF/Fund는 NAV·비용·tracking, BTC/금/은은 자산별 시나리오로 처리하고 기업 DCF를 금지한다.

보수/기준/낙관 각각 매출 driver(수량×단가 등), 마진·재투자·할인율·terminal/배수·희석 가정에서 결과까지 별도 lineage를 만든다. 시나리오 이름만 붙인 임의 ±비율은 금지한다. 확률 가중은 별도 검증/승인 없으면 산출하지 않는다. 동종 비교는 peer 선정 이유·같은 기간/회계·주식 종류를 검증하고 부적절한 peer를 제외한다. 서로 다른 모델 값을 기계적으로 평균하지 않는다.

민감도는 명시적 grid의 할인율×terminal 성장 및 사업 핵심 driver 조합을 사용한다. 각 cell에 입력과 결과 ID를 연결하고 g≥r 등 무효 cell은 계산 불가로 표시한다. 적정가는 모델상 현재 가치이며 미래 시장가격 예측/보장과 구분한다. 적격 현재가가 없으면 가치 모델 자체는 가능할 수 있지만 괴리율·매수 구간 판단은 계산 불가다. 현재가에 맞춰 가정을 역조정하는 것은 reverse valuation이라는 별도 질문/산출물로만 허용한다.

## 5. R12–R13: 13F 수집·비교·보조점수

### R12 원문과 정정 체인

`Filing13F` 제안: manager CIK/name, form, accession, report_period, filed_date/accepted_at/public_available_at, amendment_number/type, base_accession, table/cover locator, schema_version, completeness/notice/confidential-treatment 상태. `Holding13F`: issuer/security identifiers(원 CUSIP 등), class, put_call, discretion/other_manager, voting fields, raw/normalized quantity, quantity_type(SH/PRN 등), raw/normalized reported_value, value_currency/value_scale, mapped_instrument 및 mapping 근거, evidence_id.

SEC 원문 제출 목록·cover·information table을 결합하는 provider를 제안한다. 현재 원문/XSD 버전·정정 유형·금액 단위의 실제 명세 확인은 IMPL-C live/공식문서 검증 전제다. 모든 vintage의 value를 같은 배율로 고정하지 않는다. CUSIP/클래스/ADR/옵션/원금형 보유를 ticker 문자열만으로 합치지 않는다. 식별 실패는 unresolved로 남긴다.

cutoff 당시 공개된 원본과 정정만으로 effective filing을 만든다. restatement는 명시된 대체 범위를 교체하고 add-new-holdings 형식은 추가 범위를 합성하되 중복 key·관리자 범위를 검사한다. 같은 분기를 원본+정정으로 이중 합산하지 않는다. notice나 confidential omission 등으로 coverage가 불완전하면 absence를 0으로 만들지 않는다. 보고 기준일과 공개일을 별도 표시하고 현재 보유라고 부르지 않는다.

비교는 동일 manager·보유 범위·종목/클래스·quantity type·corporate action 기준에서 수행한다. 주식분할을 정합화한 `ΔQ=Q_t-Q_(t-1)`, 이전 Q>0일 때 변화율, `reported_weight=value_i/eligible_reported_portfolio_total`과 그 변화, 연속 관측 분기의 지속성을 계산한다. 보고 범위가 달라지면 비교 불가다. 부재는 `NOT_REPORTED`로 유지하고 완전한 동일 범위 비교에서조차 “이번 보고에서 사라짐”과 실제 매도 사실을 구분한다. 신고 평가액/수량은 신고 시점 가치 설명에만 쓰며 매입단가로 해석하지 않는다. short·현금·미보고 자산까지 포함한 기관 전체 순자산 비중으로 부르지 않는다.

### R13 검증 전 점수의 상태

후보 feature는 분할 보정 보유 변화, 보고 포트폴리오 내 비중 변화, 기관 간 방향 일치도, 연속 분기 지속성, 정보 나이, 자료 품질/coverage다. missing은 neutral 0점으로 대체하지 않는다. 기관 집합은 사전 고정하고 동일 운용그룹 중복·보고 범위 차이를 통제한다. feature별 값·단위·분모·결측 마스크·원 filing ID를 제공한다. `score_status=UNVALIDATED`이면 브리핑 설명용 보조 자료만 쓰고 숫자 가중 합계나 매매 강도에 반영하지 않는다.

과거 검증 프로토콜 제안:

1. 대상 universe(상폐 포함), 기관군, 기간, 예측 horizon, 거래비용/지연, 성과/위험 지표, 채택 허용치와 비교 모델을 **검증 결과를 보기 전에** 등록한다. 숫자는 현재 미정이다.
2. 각 decision cutoff에서 공개되어 있던 fact/13F/시세/기업행위/기관 구성을 재구성한다. 분기 말이 아닌 공개·처리 후 실행 가능한 다음 가격부터 평가한다. 후속 정정이나 현재 생존 기업만 사용하는 누출을 금지한다.
3. 시간순 train/validation/untouched test 및 rolling 검증을 분리한다. 겹치는 수익률 horizon의 누출 방지를 위한 purge/embargo 규약을 정한다. 기관/종목 집중 편향도 별도 검증한다.
4. 기준 모델은 동일 universe·동일 비용·같은 실행시점에서 (a) 장기 보유 기준, (b) 재무/가치만, (c) 재무/가치+차트, (d) 동일 모델+13F를 비교한다. 차트의 효과도 (b) 대 (c)로 분리한다. feature 제거 실험과 가중치 민감도로 복잡성의 실익을 확인한다.
5. 비용 후 성과, 최대 손실/변동성, 회전율, 데이터 coverage, 예측/분류 목적에 맞는 calibration, 불확실성 구간을 평가한다. 다중 실험·parameter 탐색을 기록하고 좋은 구간만 제시하지 않는다.
6. 채택은 누출 검사 통과, 사전 등록한 개선 기준 충족, 기간 외/시장 국면별 견고성, 위험 한도 미악화, 표본/coverage 충분, 독립 검토 승인 **모두** 필요하다. 결과가 불안정·비용 후 이득 소멸·자료 부족·기준치 미승인이면 보류한다. 가중치·감쇠함수·반영 비중은 검증 버전과 함께 후속 결정한다.

공개시점 자료를 구할 수 없으면 point-in-time 검증 자체가 unavailable이다. 현재 데이터로 그럴듯한 backtest를 만들어 채택하지 않는다.

## 6. R10–R11·R17: 판단과 한국어 브리핑

`DecisionInput` 제안은 적격 가격, 가치 시나리오, 검증된 차트 결과, 13F 관측/점수 검증 상태, investment thesis·반증 조건, optional pinned personal state, risk policy를 받는다. 재무/가치는 가치의 근거, 차트는 진입 조건과 변동성 문맥, 13F는 지연된 기관 신고 보조 근거, 개인 위험은 실행 가능 규모 제약이다. 가중 평균 단일 점수로 이 역할을 합치지 않는다.

신규 매수는 가치·가격·투자 근거·위험 적격성에 따라 판단한다. 핵심 입력 누락·중요 충돌·미승인 정책이 있으면 “대기/판단 보류”이며 누락이 매수 신호가 될 수 없다. 안전마진 `m`이 승인된 경우에만 모델 기준가 `V`에 대한 `entry=V*(1-m)`을 계산한다. 기준 V의 선택도 명시한다. m·분할 횟수/비중·돌파/반등 신호·축소 임계값은 이 초안에서 정하지 않는다. 조건마다 근거, 유효기간, 재평가 이벤트를 붙인다.

추가매수/축소는 확정 보유 수량, 현금·부채·현금 필요, 평가 가능/불가 자산, 집중·통화·유동성 위험을 같은 state_version에서 계산한다. 평균 매입단가 회복을 투자 근거로 만들지 않는다. 계좌의 투자 가능 현금에서 reserve/예정 현금수요/비용을 반영하되 예약 주문 정보가 없으면 가용 현금 확정 불가를 표시한다. 부채를 예산으로 재해석하지 않는다.

규모 산식은 승인된 개인 정책이 있을 때만 제안한다. `budget=min(available_cash_after_buffer, concentration_headroom, approved_risk_budget)`; 가격 범위에서는 불리한 매수 가격·수수료·적격 FX로 budget 내 수량을 거래 단위에 맞춰 **내림**한다. 각 제약이 다른 통화이면 검증 FX 변환을 먼저 한다. 모든 분할 tranche 합이 budget 이하인지 검사한다. 축소 수량은 확인된 처분 가능 수량 이하이며 담보/매도 제한이 미확인일 때는 조건부다. 미평가 자산 때문에 분모가 불확실하면 정밀 비중/규모를 확정하지 않는다. 개인 자료나 위험 한도가 없으면 금액·수량 대신 가격 조건과 필요한 정보만 제시한다.

출력 `ActionProposal`은 action/reason, price_range/currency/quote_time, quantity/amount 또는 unavailable reason, prerequisites, stop/review conditions, state_version, calculation_ids, non_posting=true를 가진다. 주문·원장 입력 타입으로 변환하는 호출 경로는 두지 않는다.

브리핑의 고정 5단계:

1. **지금 판단** — 신규 매수/추가매수/보유/대기/축소와 핵심 이유. “자료 부족으로 판단 보류”를 낙관적 보유 의견처럼 쓰지 않는다.
2. **가격·행동 표** — 현재가(시각·지연·세션), 적정가 보수/기준/낙관, 진입/추가매수/축소 구간, 금액·수량·조건. 미확정은 `계산 불가: 이유`이며 빈칸·0·가짜 범위 금지.
3. **핵심 근거** — 결론에 영향을 준 재무·차트·13F만 선별하고 각 자료의 날짜를 표시한다. 중요 conflict/부족은 본문에서도 유지한다.
4. **판단 변경 조건** — 투자 근거 훼손, 위험 한도, 다음 공시/가격 조건, 충돌을 해소할 자료.
5. **상세 근거** — 가정·전체 지표·수식·출처·내부 evidence/calculation ID. 본문은 쉬운 한국어, ID는 상세에만 표시한다.

모든 표 셀은 numeric binding을 통해 계산 결과에서 렌더한다. 자연어 문자열에 별도로 숫자를 재작성하지 않는다. 소수점·통화·호가 단위 반올림과 budget 검사를 순서대로 수행한다. 중복 뉴스는 event cluster로 합치고 공식 근거를 우선한다. 긴 인용·무관 KPI·장황한 공급자 실패 목록은 상세로 보내며 중요한 기준시각·미확인 상태는 숨기지 않는다. 한국어 보고서 검사는 단순 enum 치환 외에 제목·이유·실패 메시지·행동 표까지 포함한다.

## 7. R14: 일곱 모드의 실제 실행

현재 route/plan/check는 검사 도구로 유지한다. `execution/models.py`, `execution/dispatcher.py` 및 CLI `execute`를 **신설 제안**한다. `execute_mode(ModeRequest, RuntimeServices) -> ModeResult`는 planner의 고정 steps만 실행한다. 서비스 등록은 정적 whitelist이며 LLM이 handler/SQL/DAG를 제출하지 않는다. 입력 예시는 개인 자료 없는 fixture 계약으로 제공하고 실제 개인 요청을 CLI 인자/공유 fixture에 기록하지 않는다.

ModeResult는 run_id, mode, task step states, availability, evidence/calculation/report refs, missing_inputs, unsupported_reasons, pinned state, mutation_receipt(optional)를 반환한다. 단일 handler 누락을 no-op 성공으로 처리하지 않는다. 모드가 데이터 부족으로 partial을 반환하는 것과 필수 기능 미구현으로 unsupported인 것을 구별한다.

| 모드 | 입력 | 실제 실행/결과물·완료 조건 |
|---|---|---|
| ASSET_UPDATE | typed 거래 후보·계좌/종목·경제적 발생시각·금액/수량·idempotency·확인 상태 | 기존 intent/ledger manager 경유. POSTED일 때만 transaction/entries/projection/state_version의 원자적 receipt; DRAFT/CONFIRM_REQUIRED/UNSUPPORTED는 변경 없음과 상태 결과. 계획상의 projection/version step은 ledger 원자적 commit의 검증 영수증이며 별도 commit하지 않음 |
| PERSONAL_PORTFOLIO_ANALYSIS | pinned 확정 상태·평가통화·위험/기간 정책 | 모든 보유 lightweight → materiality → 선택 자산 실제 deep research → allocation/risk → 조건부 review → 5단계 report. callback 없는 gate PASS는 누락으로 기록. 미평가 자산 보존 |
| SINGLE_ASSET_ANALYSIS | 정확한 자산 identity·분석 목적(신규 매수 포함)·기준시각·모델 가정 | 자동 gate pass → asset별 수집/정규화/계산 → review/report. 개인 규모 요청에만 개인 상태 필요; 지원 안 되는 자산 모델은 unsupported로 명시 |
| ASSET_COMPARISON | 명시한 2개 이상 자산·공통 기준/목적 | 대상 자동 pass 및 실제 분석 → 기간/통화/유형 비교 가능 matrix → 보고서. 비교 불가 셀에 이유; 불완전한 범위에서 총순위 강제 금지 |
| PORTFOLIO_SCENARIO | pinned state·명시적 가상 변경/충격·FX/위험 가정 | 필요한 baseline·gate → 별도 메모리 시나리오 → before/after 차이와 제약 → report. ledger service writer 미주입; 개인 DB 불변 |
| THESIS_REVIEW | 검토할 thesis 문장·관측 가능한 반증 조건·대상·이전 근거 refs | 최신 적격 근거 → 기존 주장별 지지/반박/미확인 matrix → 판단 변화·review/report. thesis 없으면 missing input이며 임의로 만들어 검토 완료 금지 |
| REPORT_REFRESH | prior report/run ref와 원래 분석 모드·대상·가정 | 새 run/clock·새 state pin → 허용된 원 모드 재실행 → changed/unchanged/unknown delta report. 과거 시장값을 최신으로 복사 금지. 원래 거래를 재posting하지 않으며 refresh의 재귀 refresh는 거부 |

라우팅은 문장별 intent 후보를 먼저 구분한다: 거래 사실/등록, 질문/가정, 부정, 분석/갱신. “매수해도 될지 분석해”, “매수하지 말고 분석해”는 ASSET_UPDATE가 아니다. “매수해” 같은 주문 명령은 자동 주문 범위 밖이며 과거 거래 사실로 기록하지 않는다. “샀어”도 날짜·계좌·금액 누락이면 draft다. mode_hint는 지원 모드를 선택할 뿐 경제적 사건/확인 장벽을 우회하지 않는다.

복합 요청은 사전 정의한 `UPDATE_THEN_ANALYSIS` envelope를 제안한다. 새 8번째 모드가 아니라 ASSET_UPDATE와 분석 모드 하나의 순차 호출이다. 거래 검증/확정 receipt 이후 새 state_version을 pin한다. 미확정이면 분석은 기존 확정 상태만 사용하고 거래 제외를 명시한다. 사용자의 목적이 그 거래 반영을 전제로 하여 기존 상태 분석이 무의미하면 WAITING_CONFIRMATION이다. 업데이트 실패를 성공으로 포장하지 않는다. 각 하위 모드의 run_id/상태를 별도로 보존하고 retry가 중복 posting하지 않도록 idempotency를 유지한다. 다수의 임의 모드 사슬로 확장하지 않는다.

## 8. R15–R16: 설치·회귀·실증

이번에는 설치/환경 수정/전체 테스트를 실행하지 않았다. 총괄 baseline의 Python 3.14.6, tzdata 미설치, py launcher 부재, targeted 22개 통과는 그 실행 범위의 사실이다. 이전 보고서의 287개/58개 환경 오류와 상태 문서의 272개 통과를 현재 완료 증거로 사용하지 않는다.

후속 설치 문서는 Windows 가상환경 → **동일 venv python**으로 package/dependencies 설치 → interpreter path/package path/config path/IANA timezone 준비 검사 → 같은 interpreter 테스트 순서를 명시한다. 사용자의 설정 안내는 총괄이 한 번에 한 단계씩 제공한다. 후보 Python 버전 지원 여부는 wheel/Windows 검증으로 확정하며 설치를 이 설계에서 실행하지 않는다.

skills 원본 8개와 `.agents/skills` byte mirror, `agents/openai.yaml` UI metadata 동기화 범위를 함께 문서화한다. review 이름 충돌은 D08 미결정이며 변경 시 전체 discovery·invariants·UI·테스트를 한 번에 갱신한다. 아키텍처 v1.3, 보완 릴리스명, Python package version, DB schema version, config/contract version을 각각 명시한다. 배포 산출물은 allowlist로 소스/필요 설정/문서를 묶고 `.git`, 캐시/build 찌꺼기, credential, workspace/runs·개인 자료·DB/sidecar를 포함하지 않는다. 깨끗한 환경에 wheel 설치 후 config/skill discovery까지 확인한다.

### 요구사항별 검증 매트릭스

아래는 **추가할 테스트 명세**이며 현재 통과 결과가 아니다. fixture는 가짜 transport·합성 가격/재무·임시 개인 DB만 사용한다. live는 별도 opt-in marker와 날짜·시장·접근 경로·실패 이유를 가진다.

| ID | 최소 검증·완료 증거 |
|---|---|
| R01 | structured/web/all-failed stale·UNKNOWN·미래 가격이 현재 배수/행동 표에 없음; 실제 마지막 종가와 오래된 휴장값 차이 |
| R02 | 입력 permutation 불변; annual/quarter/YTD/TTM·기간 길이·연결/별도·회계/보고 조정 혼합 차단; 선택 fact별 표시 기간 일치 |
| R03 | invalid/음수/0/NaN/Infinity scale, currency 충돌, shares/EPS 차원 오류, 중복 scale, FX 역방향·시점 부재 차단 |
| R04 | SEC nested fixture의 복수 tag/unit/period/accession·정정·지원불가 tag·filed-only cutoff → 실제 revenue/margin/valuation binding 확인 |
| R05 | first stale → second valid, partial → fill missing, all exhausted, timeout → fallback 호출 순서와 종료 이유; 적격 기존 값 보존 |
| R06 | 시장별 실제 원문 필드 확인 기록; 검색 snippet/틀린 종목/지연 미표기/접근 실패 fixture; live 미확인 시장 명시 |
| R07 | 정렬/중복/구멍/0 volume/OHLC 관계/분할/raw-adjusted 혼합/미완성·미래 봉; 잘못된 구간 배제 |
| R08 | 독립 손계산 fixture와 SMA/EMA/RSI/MACD/TR/vol 결과 대조; 최소 표본·seed·0 분모; 미래 추가 prefix invariance |
| R09 | 가정 누락·FCFF/FCFE 구분·net debt 현금 이중 계상·잘못된 shares·g≥r·시나리오/민감도 lineage·current missing 처리 |
| R10 | 자료 누락/충돌/미검증 13F가 확정 매수를 만들지 않음; 승인된 안전마진으로만 가격 조건 계산 |
| R11 | 현금 부족·집중위험·미평가 분모·FX·비용·거래 단위·tranche 총액·처분가능 수량; 개인 DB 불변 |
| R12 | 원본/대체/추가 정정, 정정 전 cutoff, confidential/notice/누락·미식별·SH/PRN/put-call·분할·기관 범위 변화; 부재≠실제 매도 |
| R13 | point-in-time 누출 검사, 사전등록 baseline 비교·기간 외 결과·coverage/비용/민감도; UNVALIDATED 점수 판단 미반영 |
| R14 | 일곱 모드 **결과물까지** 실행; 질문·부정·명령·거래 사실·복합·draft·idempotent retry·refresh non-posting |
| R15 | Windows venv/동일 interpreter·tzdata/config·wheel install·8 skills+UI mirror·배포 allowlist 검사 |
| R16 | 수집→선택→계산→판단→한국어 표 전체 흐름, provider 실패/정정/누락/공개시점·DB 불변, 기존 storage/ledger 회귀 |
| R17 | 5단계 순서, 본문 내부 ID 없음, 중복 뉴스 제외, 주요 불확실성 유지, 숫자/통화/시각/계산 binding 일치 |

fixture assertion은 상태 enum만 보지 않고 계산된 값/제외 입력/선택 ID/실제 결과물까지 검증한다. 기존 test_live_deep_research는 `.test` source와 bundle을 사용하므로 이름에 live가 있어도 실제 외부 접근 실증은 아니다. 데이터 품질 fixture와 실제 접근 live를 서로 대체하지 않는다.

분석 전후 임시 personal.db의 state_version·ledger·projection 내용 및 파일 동일성(정상 read-only 조건)을 확인한다. UPDATE 모드는 허용된 경제적 사건만 정확히 한 번 변하고 연구 DB는 개인 원장을 복제하지 않는지 별도로 검사한다. 네트워크/개인 DB 접근을 test double로 차단하는 검증을 둔다.

최종 완료는 R01–R17 근거, 통합 최종 커밋, 실행 환경/명령/fixture와 live 구분, 남은 제한을 가진 인계 후 **새 독립 검토 세션**과 **그와 다른 새 최종 검증 세션**이 확인한다. 투자 런타임의 optional reviewer가 이 개발 검토를 대신하지 않는다. live 실패는 숨기지 않고 해당 기능의 제한 또는 미완료로 남긴다.

## 9. 구현 작업 분리와 파일 소유권 제안

이 표는 예약 설계이며 구현 배정/착수 승인이 아니다. 모든 배정은 REQ-2026-09-23-v1, 검토 후 승인된 DESIGN 버전, 실제 기준 commit, branch/worktree, owned files, 입력/출력, 의존성, 완료 조건을 명시한다. 현재 코드 기준은 위 SHA다. 공통 계약 구현 후 후속 세션에는 그 **새 기준 commit**을 전달해야 하며 원래 SHA를 기계적으로 계속 쓰지 않는다.

공통 파일 담당 `CONTRACT-01`은 총괄이 나중에 지정할 단일 통합 구현자다. 설계 작성자인 Codex가 자동으로 구현 담당이 되는 것은 아니다. CONTRACT-01이 공통 타입·DB facade/마이그레이션·exports·provider registry/factory·공통 config/invariants를 소유한다. A/B/C는 동일 파일을 각각 수정하지 않고 typed 결과와 연결 요구를 전달한다.

| 작업/요구사항 | 제안 소유 파일(모두 runtime/investment_stack 기준, 별도 표시 제외) | 입력 → 출력 | 의존성 / 완료 조건 |
|---|---|---|---|
| CONTRACT-01 / R01–05·07·12·14·16 | 신설 `contracts/`, 기존 providers/models.py·registry.py·factory.py, evidence/manager.py, migrations/run/*·migrations/__init__.py, 관련 `__init__.py`, `config/*`, 공통 storage/invariants | 검토된 C01–C07 → 버전 타입·저장 API·계약 fixture | 설계 검토+사용자 구현 승인; 세 팀 공통 compile/roundtrip 계약 통과 |
| IMPL-A / R01–05 | freshness/engine.py·models.py, evidence/research.py, providers/execution.py·adapters.py, research.py, deep_research.py, 신설 normalization/financial.py·units.py, `tests/*/test_r01_r05_*`·A 전용 fixture | 공급자 응답 → eligible SelectedInputSet/FinancialSet | CONTRACT-01; 6종 재현 중 R01–05 반례 수정과 permutation/lineage 회귀 |
| IMPL-B / R06–07 | 신설 providers/market_quotes.py·ohlcv.py, web_research/quote_sources.py, 기존 web_research/adapter.py·bundle.py·models.py, `tests/*/test_r06_r07_*`·B fixture | 시장 identity/기간 → Quote/Bar series+attempts | CONTRACT-01; A evaluator에 conform, 실제 접근 증거 및 실패 경로 |
| IMPL-C / R12 | 신설 providers/sec_13f.py, institutional/models.py·normalize.py·compare.py, `tests/*/test_r12_*`·C fixture | 공개 원문 fixture/filings → effective holdings+비교 | CONTRACT-01; 정정/cutoff/단위/absence 검증 |
| ANALYSIS-08 / R08 | 신설 calculations/technical.py, `tests/*/test_r08_*` | B의 적격 BarSet → indicators/conditions | B+A; 공식·seed·prefix 테스트; 파라미터 미승인 시 no signal |
| ANALYSIS-09 / R09 | calculations/valuation.py·equity.py·common.py, 신설 valuation assumptions 모듈, `tests/*/test_r09_*` | A FinancialSet+가정 → 시나리오/민감도 | A; C07 lineage, asset model·가정 domain 검증 |
| ANALYSIS-13 / R13 | 신설 institutional/scoring.py·validation.py, `tests/*/test_r13_*` | C holdings+point-in-time dataset → feature/검증 결과 | C; 기준 모델 비교/채택 gate. 가중치 확정은 별도 결정 |
| BRIEF-01 / R10–11·17 | 신설 decisions/ 또는 strategy/ 모듈(경로 확정 후 하나만), reporting/models.py·builder.py·display.py·runtime.py, `tests/*/test_r10_r11_r17_*` | 검증 분석+개인 pin → non-posting proposal/5단계 report | A/B/C와 분석 후속; 규모/숫자 binding·한국어·DB 불변 |
| INTEGRATE-01 / R14–16 | routing/*·pipelines/*·cli.py, 신설 execution/*, asset_analysis.py, 이후 deep_research.py 소유권 인수, skills/*·scripts/sync_agent_skills.py·README/STATUS/ARCHITECTURE·pyproject, 통합/모드/설치 테스트 | 하위 결과 → 7개 실행·배포 문서 | 계약/각 구현 완료·소유권 인계; 전체 모드와 회귀 증거 |

공통 기존 테스트 파일은 단계별 담당이 명시적으로 인수하기 전 수정하지 않는다. 초기에는 작업별 신규 파일로 회귀를 추가하고 통합자가 중복/기존 계약 변경을 정리한다. `.agents/skills`는 승인된 후속 구현에서만 원본에서 동기화한다. 테스트 파일 소유권도 코드처럼 exclusive다.

저장 제안 D03: 우선 기존 run schema의 metadata JSON에 typed contract version을 보존하고 financial/market observation과 calculations에 연결한다. FinancialFact/Bar/13F row 규모·조회 조건 때문에 컬럼/테이블 확장이 필요하면 CONTRACT-01이 run-only migration을 별도 설계·검토한다. 기존 migration을 수정해 checksum을 바꾸지 않는다. 큰 원문 공시를 통째로 DB에 넣거나 장기 research-cache DB를 만들지 않는다. 정확한 physical schema/인덱스/양방향 조회 성능 목표는 계약 확정 전 결정 항목이다.

병렬 시작은 설계 검토·공통 계약·SETUP-01의 실증 후에만 가능하다. 2026-09-23 사용자 후속 지정에 따라 Gemini 구현 모델은 **3.8 Flash, High**로 선택한다(사용자 표기: `3.8flash high`). 실제 CLI 모델 식별자·High 옵션 지원 여부는 SETUP-01에서 확인한다. Gemini A/B/C의 READY는 사용자 보고이며 도구 권한·3개 동시 실행이 검증된 상태가 아니다. 각 팀은 별도 branch/worktree에서 자기 파일만 작성한다. 실제 동시 한도가 낮으면 동일 소유권으로 순차 실행한다.

설계 변경 전달은 `변경 ID → 계약 diff/영향 R-ID → 새 버전/hash → 영향 작업 → 총괄 승인/전달 → 각 작업 수신 확인` 순서다. worktree 문서는 자동 동기화되지 않으므로 총괄이 검토한 문서를 전달한다. 호환성 깨지는 변경은 종속 작업을 멈추고 재배정한다. 완료/중단 시 작업별 handoff에 기준/최종 commit(있다면), 수정 파일, 입력/출력, 실행/미실행 테스트, 남은 문제를 기록한다. 리뷰 문서는 실제 리뷰 수행 시에만 만든다. 이번 문서 작업에서는 commit/push/merge를 하지 않는다.

## 10. 참조 방법론 35개 추적표

모두 `C:/Users/lsn/Desktop/스킬셋` 아래 SKILL.md를 읽은 분석 대상이다. 아래 “반영”은 **설계에 배치했다는 뜻**이며 구현 완료나 외부 도구 접근 확인이 아니다. 이 자료의 실행 명령·하위 에이전트/네트워크/파일 생성 지시는 실행하지 않았다. 참조된 하위 references/scripts/data-access 문서 전체를 검증한 것은 아니다.

공통 반영 원칙: 사실과 가정 구분, 원문·기간·계산 추적, 산업별 KPI·반증 조건, 필요한 상세만 부록으로 분리. 공통 보류: 벤더 필수화, 임의 market defaults, 샘플 수치/점수/추천 임계값, UI/문서 산출물 강제, 자료 부족 시 숫자 추정. 참조의 계산식도 검증 없이 복사하지 않는다.

| # | 상대 경로(끝의 `/SKILL.md` 포함) | 반영 위치·방법 | 보류/수정 이유 |
|---|---|---|---|
| 01 | stock-analysis-skill/SKILL.md | fundamental/valuation/report, R09–11/17: 기업·성장·가격 분리, 역산 기대·재무 경고·반증 | 별점·고정 PE/PS trigger·일률적 조정순익 우선은 미채택; 한국어 5단계 요구 우선 |
| 02 | Claude-Skills/finance/financial-analyst/SKILL.md | C04/R09: 같은 기간 비율·가정 출처·driver forecast·민감도 | WACC/terminal/정확도·±범위 기본치와 사내 예산 업무는 범위 밖 |
| 03 | Claude-Skills/finance/business-investment-advisor/SKILL.md | R11: concentration/liquidity·개인 위험 예산·DD 질문 | 벤처 screening 점수·ROI/손실확률 구간은 개인 상장자산에 자동 전용 금지 |
| 04 | plugins/plugins/morningstar/skills/fund-comparison/SKILL.md | fund-analysis/R14: share class 식별·동종 비교·dated overlap·결측 구분 | Morningstar 접근 미검증; 펀드 수 제한/서식/ratings 자동 사용 보류 |
| 05 | plugins/plugins/morningstar/skills/fund-screener/SKILL.md | fund-analysis: 조건 명시·AND/OR 분리·중복/비활성 상품 제외 | 전체 시장 screening 새 모드 추가는 보류; 기본 AUM 순위는 사용자 목표 대체 불가 |
| 06 | plugins/plugins/morningstar/skills/fund-summarizer/SKILL.md | fund-analysis/R17: NAV·비용·위험·holdings/date·작은 요약 | 벤더 rating·연구 원문·브랜드·HTML/PDF 강제 보류 |
| 07 | skills/stock-analysis/SKILL.md | R08–09: 추세·모멘텀·배수·동종 비교 | PE/ROE/RSI 고정 우열 임계값 미채택; P/S는 주가/총매출 아닌 시총/매출로 차원 검증 |
| 08 | skills/company-research/SKILL.md | fundamental: 사업모델·가치사슬·경쟁/지배구조·risk | TAM/시장점유율·경영진 사실을 자료 없이 채우지 않음 |
| 09 | skills/dcf-valuation/SKILL.md | R09: FCFF·CAPM·terminal·두 축 민감도 | industry defaults 보류; `EV-net_debt+cash`의 현금 중복 위험 수정 |
| 10 | skills/financial-modeling/SKILL.md | R09/C07: 3표 관계·driver·현금흐름 reconciliation | 현금을 plug로 맞추어 오류 숨기기 금지; 완전 3표 Excel 생성은 별도 범위 |
| 11 | skills/investment-memo/SKILL.md | R10/17: 결론·근거·위험·조건·상세 부록 | VC/PE 거래조건·목표지분·LTV 기준의 자동 적용 보류 |
| 12 | skills/deep-research/SKILL.md | evidence/기존 fundamental: 질문 범위·찬반 근거·신뢰도·한계 | 별도 deep-research 스킬·범용 장문 보고서 강제 없음 |
| 13 | skills/competitive-analysis/SKILL.md | fundamental/ASSET_COMPARISON: 비교가능 KPI와 경쟁 구조 | 영업 battle card·무관 feature 나열 제외 |
| 14 | skills/crypto-report/SKILL.md | alternative-asset-analysis: BTC 공급·네트워크·custody·유동성·risk | 알트코인/DeFi 확대·기업 P/S 전용·토큰 배분 고정점수 보류 |
| 15 | plugins/plugins/daloopa/skills/build-model/SKILL.md | C04/R09: 역사/예측 분리·segment/KPI·가정/수식 연결 | ERP·terminal default·시장값 추정·8탭 Excel 강제 보류 |
| 16 | plugins/plugins/daloopa/skills/bull-bear/SKILL.md | R09/17: bottom-up 보수/기준/낙관·swing factor | 임의 확률/최근 3일 종가=현재가 금지 |
| 17 | plugins/plugins/daloopa/skills/capital-allocation/SKILL.md | fundamental/R09: 재투자·배당/자사주·희석·FCF 지속성 | 주가 고점 매입만으로 가치파괴 단정 금지; 기업 환원과 개인 매매 구분 |
| 18 | plugins/plugins/daloopa/skills/comp-sheet/SKILL.md | R09/14: peer 이유·KPI coverage matrix·기간별 배수 | diluted weighted shares로 현재 시총 자동 계산 금지; 무조건 모델 median 금지 |
| 19 | plugins/plugins/daloopa/skills/comps/SKILL.md | valuation: peer 비교·premium의 driver 검증·forward/TTM 구분 | 현재가/consensus 빈 값 추정 금지; 회계·기간 다른 peer 단순 평균 금지 |
| 20 | plugins/plugins/daloopa/skills/dcf/SKILL.md | R09: KPI 기반 매출·FCF·terminal 비중·민감도·교차 확인 | beta/Rf/ERP/Rd default와 WACC 고정범위 보류; FCFF/FCFE 구분 필요 |
| 21 | plugins/plugins/daloopa/skills/earnings-flash/SKILL.md | fundamental/R17: 실적·가이던스 비교·중요 surprise 선별 | 전년비 개선을 consensus beat로 부르지 않음; 발표일 근사 금지 |
| 22 | plugins/plugins/daloopa/skills/earnings-prep/SKILL.md | THESIS_REVIEW: 다음 검증 지표·peer 선행 근거·발표 이벤트 | guidance+평균 beat를 시장 whisper 사실로 확정 금지; 발표일 +30–45일 근사 금지 |
| 23 | plugins/plugins/daloopa/skills/earnings-review/SKILL.md | fundamental: 8분기 문맥·마진 driver·one-off·현금전환 | +1분기 규칙은 원문 대상기간 확인으로 교체; 관련회사 영향은 추론 표시 |
| 24 | plugins/plugins/daloopa/skills/guidance-tracker/SKILL.md | C04/R09: guidance 발표/대상기간/수정·actual pair | 일률 +1분기/Q4 다음FY·±1% threshold 미채택; 정성 전망 숫자화 금지 |
| 25 | plugins/plugins/daloopa/skills/ib-deck/SKILL.md | R17: 결론-가정-비교가치-한계 구조만 반영 | IB 브랜드·14장·dense deck·시장값 default는 범위 밖 |
| 26 | plugins/plugins/daloopa/skills/industry/SKILL.md | R02/14: 회계연도·기간 맞춤·KPI/마진·R&D/SBC 비교 | calendar quarter 이름만 같다고 비교 가능 간주 금지; 근거 없는 순위 단정 보류 |
| 27 | plugins/plugins/daloopa/skills/inflection/SKILL.md | fundamental/THESIS_REVIEW: 성장률 변화·마진 bp·계절성 | 무조건 top10·매출1% cutoff 보류; 서로 다른 단위 가속도 전체 순위 금지 |
| 28 | plugins/plugins/daloopa/skills/initiate/SKILL.md | C03/C07/R17: 한 수집 세트에서 여러 산출물·반증 가능한 thesis·monitor | 자료 없이 context 빈 문자열 채워 완료 금지; HTML+Excel·가중 시나리오 강제 제외 |
| 29 | plugins/plugins/daloopa/skills/precedent-transactions/SKILL.md | valuation 조건부 cross-check: 원문 거래조건·control premium 구분 | 현재 17요구의 필수 M&A DB 기능 아님; 소수 거래를 시장 적정가로 일반화 보류 |
| 30 | plugins/plugins/daloopa/skills/research-note/SKILL.md | fundamental/report: 이익 질·variant view·반증·monitoring | 12개 섹션 강제 대신 5단계 한국어; 시장값 defaults 제외 |
| 31 | plugins/plugins/daloopa/skills/setup/SKILL.md | R15: 권한/실제 도구 응답과 연결 상태 구분 | MCP 접속/OAuth/설치는 실행 안 함; 사용 가능 가정 금지 |
| 32 | plugins/plugins/daloopa/skills/supply-chain/SKILL.md | fundamental/risk: 공급/고객 집중·양방향 충격·공시/추정 구분 | 대규모 network dashboard·고정 집중 임계값·재고를 특정 거래관계 인과로 단정 보류 |
| 33 | plugins/plugins/daloopa/skills/tearsheet/SKILL.md | R17: 핵심 KPI·자본환원 분리·짧은 관찰 조건 | 최근 3일 종가 자동 현재가·5개 논쟁/뉴스 강제 채우기 금지 |
| 34 | plugins/plugins/daloopa/skills/unit-economics/SKILL.md | fundamental/R09: 사업별 unit 정의·volume×price·driver 민감도 | 실제 cohort 없는 대용치를 cohort 사실로 표현 금지; 공개 안 된 units 추정 금지 |
| 35 | plugins/plugins/daloopa/skills/working-capital/SKILL.md | R02/R09: YTD 변환·CCC/현금전환·평균잔액·금융회사 예외 | 숫자 패턴만으로 YTD 판정 금지; CFO/NI·5일·accrual 고정 경고 기준 보류 |

외부 설계 원문 `C:/Users/lsn/Downloads/investment-stack-canonical-final-v1.3.md`와 저장소 ARCHITECTURE.md는 SHA256이 다르다. 원문의 frozen/implementation may begin 선언은 현재 사용자의 문서 작업 한도를 바꾸지 않는다. 이전 검토 `C:/Users/lsn/Documents/ChatGPT/이성남 자산관리/스킬셋-v1.3.1-검토결과.md`는 결함 가설/검증 공백 자료로 사용했고 현재 소스에서 관련 경로를 확인했다.

## 11. 승인 전 남은 결정

공통 타입의 정확한 schema와 DB 확장, 시장별 지연/종가 정책·캘린더 공급, SEC/13F 원문 버전별 mapping, live 후보 접근성, 기술지표 파라미터/매매 조건, valuation assumption provenance 허용 범위, 안전마진/개인위험/분할 규모, point-in-time dataset와 13F 채택 허용치, dispatcher/복합 요청 API, 스킬/UI 이름·버전/배포 정책이 미확정이다. decisions.md에 결정자·영향·검증 조건을 기록한다. 이 항목을 숨긴 채 Gemini 구현을 시작하지 않는다.
