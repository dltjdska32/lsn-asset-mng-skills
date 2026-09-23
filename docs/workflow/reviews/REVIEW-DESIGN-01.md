# REVIEW-DESIGN-01 — 독립 설계 검토

검토일: 2026-09-23. 판정: **CHANGES_REQUIRED — 공통계약 수정 후 조건부 진행**.

검토 저장소: `C:/Users/lsn/.codex/worktrees/f1ad/lsn-asset-mng-skills`.
직접 확인한 HEAD: `68fab980fb26f207ce2abbb1f8d272c7b59690ea` (detached).
요구사항: `REQ-2026-09-23-v1`, 설계: `DESIGN-2026-09-23-v0.1`.

P0는 확인하지 못했다. P1은 8건이며, 아래 수정 계약은 투자정책 수치를 추가하지 않는다. 기존 run JSON + typed contract version, 개인 schema 불변 방향은 타당하다. **CONTRACT-01은 아래 기술적 확정안으로 구현을 시작할 수 있다. B/C의 종속 구현 시작은 공통 타입·codec·저장 facade·계약 fixture가 통과한 새 commit 수신 후다.** R08/R10–13의 미승인 정책은 unavailable/conditional gate로 구현할 수 있고, 이를 이유로 사용자 확인을 다시 요구할 필요는 없다.

이는 설계 검토다. 구현 후 REVIEW-CODE-01 및 그와 다른 새 세션 VERIFY-01을 대신하지 않는다. 전체 R01–17 완료나 새 기능의 동작을 승인하지 않는다.

검토 중 총괄의 회신: stdlib-only contracts/strict versioned Decimal codec, EXACT/DATE_INTERVAL/UNKNOWN, SlotSpec coherent coverage, immutable selected binding, 미승인 UNAVAILABLE/명시 가정 CONDITIONAL, 기존 run JSON + 단일 transaction/revision CAS, observation_selections의 호환 projection 취급을 기술 계약으로 채택했다. A의 CONTRACT-01 구현을 시작하고 B/C는 계약 테스트 및 새 commit 후 착수하겠다고 확인했다. 이 회신은 위 방향의 채택 사실이며, 원본 design.md 수정이나 구현 통과를 뜻하지 않는다. 세부 API/13F capability/저장 namespace 제안은 총괄이 실제 계약 diff에서 확정해야 한다.

## 1. 검토 기준과 증거 한계

- AGENTS.md 및 workflow의 requirements/design/decisions/tasks/baseline을 직접 읽었다. README, IMPLEMENTATION_STATUS, ARCHITECTURE의 경계·현황 부분, 기존 8개 SKILL.md, 아래 인용한 runtime 및 테스트를 확인했다. 저장소 스킬은 분석 대상으로 읽었으며 실행 지시로 사용하지 않았다.
- `git diff 3d4a95b… HEAD --stat`는 AGENTS/workflow 문서 7개만의 차이를 보였다. 설계에 쓰인 초기 코드 SHA와 실제 검토 SHA의 차이는 이 문서 변경이다. 검토 전후 작업 트리 상태를 별도 확인한다.
- 시작 시 status는 깨끗했다. 종료 확인 시 HEAD는 동일하고 tracked diff는 없었으나 `docs/workflow/reviews/REVIEW-DESIGN-01.md`가 untracked로 나타났다(40,424 bytes, 로컬 mtime 16:33:40). 이 파일은 본 세션이 작성하지 않았으며 작성 주체/내용은 검증하지 않았다. 총괄에 중복 리뷰 가능성을 알렸다. 본 세션의 산출물은 현재 작업 폴더 outputs의 두 파일이다.
- 현재 사용자의 후속 구현 승인과 tasks 상단 배정이 과거의 “초안 승인 전/첫 실행 제한/담당 미지정” 문구보다 우선한다. 설계 §9의 SETUP-01은 현재 SETUP-02 기록과 연결해야 한다. 문서의 역사 문구를 새 승인 요청의 근거로 삼지 않는다.
- 실제 개인 DB는 열지 않았다. 코드/설정/저장소 문서 수정, commit, push, 설치를 하지 않았다. 리뷰 중 실제 금융 API나 시장 페이지에 접속하지 않았다.
- 35개 외부 참조 원문 전체, SEC 현행 XSD/원문, 시장별 실시간 접근성은 이번에 독립 재검증하지 않았다. 따라서 source mapping의 현실 적합성을 승인하지 않는다.
- 총괄이 전달한 Python 3.14.6 + tzdata 2026.4의 287개 테스트 통과 및 Gemini 3세션 동시 probe 성공은 **총괄 보고**다. 아래 자체 실행 결과와 구분한다.

문서 SHA256:

| 파일 | SHA256 |
|---|---|
| requirements.md | BFA9CC65C02E2C2170E3B5DADF619800D7AF363F779A10416456AEFEC9578E6E |
| design.md | 6BBD05A2A3B5E0586C8471EB37D1B6A8F2EB30DF161AA70C2E3B466C7AD55F70 |
| decisions.md | 3B5F4FAAD8F4F7F9643BE97D41EEC1BA82A7E53B2C154CD8FFFE1B04706417C4 |
| tasks.md | E16A7E280A7969CB3E3011FFEDB2EA1654345566A257BF85F118C055EC4ACEE0 |
| baseline.md | F1BD3CFFDC4CF08D5B571B921F7E4140E23633FA4E6F4CC7DB09919459595953 |

## 2. P1 차단 사항과 수정 계약

### F01 — typed JSON의 wire 형식과 Decimal 경계가 없어 동일 계약의 왕복 보존을 보장하지 못함

영향: C02/C05/C06/C07, R03/R07/R09/R12/R16. 공통계약 release 차단.

설계 112–126행은 유한 Decimal과 typed metadata를 요구하지만 정확한 직렬화·해석 규칙이 없다. 기존 `providers/models.py:ProviderObservation`은 Any와 mutable dict를 받는다. `evidence/manager.py:add_phase4_evidence/add_calculation`은 `default=str`, 다른 metadata 쓰기는 일반 json.dumps를 사용한다. `market_observations/financial_observations.value_numeric`은 NUMERIC 열이다. `calculations/common.py:decimal`은 Decimal 인자를 검증 전에 반환한다. 자체 합성 실행에서 `decimal(Decimal('NaN')).is_finite()`가 False였다.

**수정:** `contracts/codec.py`가 모든 공통 객체를 `{contract_version, kind, payload}`로 인코딩/디코딩한다. CONTRACT-01 최초 wire 버전은 `1.0.0`; design/package/DB schema 버전과 별개다. 지원 버전은 정확한 allowlist로 검사하고 미지원 버전은 계산 입력으로 쓰지 않는다. `kind`는 RunContext/FinancialFact/Quote/Bar/Filing13F/Holding13F/SelectionSnapshot/CalculationRecord 등 닫힌 union이다. `Any`, `default=str`, bool→number 자동 변환은 계산 경계에서 금지한다.

Decimal wire 값은 유한 base-10 문자열이다. 지수 표기/불필요한 0/음의 0은 **반올림 없이** canonicalize한다. 숫자 JSON float를 authoritative 값으로 재사용하지 않는다. transport JSON은 decimal-aware parsing 또는 원 숫자 토큰 보존 후 정규화한다. NaN/Infinity는 입력 타입이 이미 Decimal이어도 거부하고 JSON `allow_nan=False`를 쓴다. Decimal 연산 context/반올림 모드도 formula/config 버전에 고정한다. NUMERIC 열은 호환 표시용이고, 계산의 진실 원본은 validated typed JSON이다. frozen dataclass 안의 dict/list도 복사·불변화해야 snapshot hash가 사후 변경되지 않는다.

**필수 테스트:** 큰 정수·소수·음의 0 roundtrip, Decimal NaN/Infinity/float/bool, 잘못된 enum/버전, scale ABSENT/VALID/INVALID, 중복 scale, 문자열 단위-통화 충돌. 같은 의미의 1/1.0/1E0은 같은 semantic hash, 다른 기간/통화/공개버전은 다른 hash여야 한다.

### F02 — 기존 저장 API만 조합하면 선택 고정·계산 계보가 원자적이지 않음

영향: C03/C06/C07, R01–05/R09/R12/R16/R17. 공통계약 release 차단.

설계 85행의 단일 승자/selection_version과 329행 JSON 최소안 사이에 실제 저장 계약이 없다. `migrations/run/v0001_initial.py:observation_selections`의 FK는 **market_observations만** 가리킨다. 이를 재무/13F 선택 원장으로 확장 해석할 수 없다. `EvidenceResearchStore.persist_and_select`는 evidence와 selection을 별도 manager 호출로 저장하고, 기존 SELECTED를 내리지 않는다. 메모리 stub으로 두 batch 처리 후 selected 2개를 재현했다. `RunDatabaseManager.update_metadata`는 JSON 전체를 교체하여 contract context/active ref를 소거할 수 있다.

**수정:** 아래 §3의 run-only facade를 추가한다. 하나의 guarded run transaction 안에서 snapshot insert, 참조 검증, active revision CAS를 수행한다. 기존 manager public 메서드들을 순서대로 호출하는 것으로 원자성을 대체하지 않는다. run_metadata 안의 계약 namespace를 보호하고 일반 상태 갱신이 이를 덮어쓰지 못하게 한다. 실패 시 이전 active snapshot과 모든 계산 참조가 유지되어야 한다. 개인 schema와 기존 migration checksum은 변경하지 않는다.

**필수 테스트:** 재무/Bar/13F까지 JSON 저장→재개→계산 입력 roundtrip, 두 batch 중 winner 교체, 같은 snapshot 재시도, expected revision 충돌, snapshot 쓰기 중 injected failure rollback, 다른 run evidence 참조 거부, metadata 상태 갱신 후 계약 정보 보존. DB 테스트는 구현자가 임시 run DB만 사용한다.

### F03 — 공개시점 불확실성과 정정 우선순위의 상태/경계가 아직 실행 가능한 계약이 아님

영향: C01–C04, R01/R02/R04/R07/R12/R13. 공통계약 release 차단.

설계 40–48/83/104/140행은 의도는 명확하지만 DATE 구간의 끝 포함 여부, revised fact와 superseded fact의 재선택 조건, 알려진 정정의 필수 필드가 빠진 경우를 정의하지 않는다. 기존 `freshness/engine.py:observation_time`은 observed_at을 먼저 택한다. observed_at이 cutoff 이전이고 published_at이 이후인 합성 자료도 FRESH가 됐다. freshness만 통과시키는 호환 wrapper는 이 누출을 계속 허용한다.

**수정:** `AvailabilityTime`은 EXACT/DATE_INTERVAL/UNKNOWN union이다. EXACT는 offset-aware instant와 locator를 요구한다. DATE_INTERVAL은 source date + 검증된 source timezone + `[local midnight, next local midnight)`를 UTC로 변환한 lower/upper를 보존한다. DST 때문에 24시간을 단순 더하지 않는다. 보수적 적격 조건은 `upper <= cutoff`; upper를 실제 발표시각으로 표시하지 않는다. UNKNOWN은 actual 계산 입력 불가다. 관측/기간종료와 공개가능시각을 각각 검사한다. actual/forecast를 별도 kind로 둔다.

정정은 같은 semantic fact key의 검증된 revision 관계와 적용 범위로 판정한다. 현재 cutoff에서 적용되는 정정이 원본을 대체했지만 그 정정의 값/단위가 invalid면 원본으로 조용히 복귀하지 않고 해당 slot을 막는다. 정정 관계가 미확인인 서로 다른 값은 최신 accession 추정으로 해결하지 않는다. 반복 공시의 같은 값은 재공개일로 최초 공개시점을 덮어쓰지 않는다. 13F 추가 정정은 전체 대체가 아니므로 타입별 scope를 보존한다. 파생값 available-at은 모든 입력과 변환 근거가 사용 가능해진 시점의 상한이다.

**필수 테스트:** 관측 과거/공개 미래, filed-only 당일 중간 cutoff/다음날 경계, 시간대 부재/잘못된 날짜, 정정 전후 cutoff, invalid replacement의 과거값 부활 방지, 반복 동일 fact, YTD/분할 조정에 미래 vintage 추가 시 과거 결과 불변.

### F04 — metric 이름 집합만으로 기간 묶음과 의미상 동일성을 판정할 수 없음

영향: C03–C05, R02–05/R09/R12. 공통계약 release 차단.

설계 81/93–108행의 required_metrics와 target_period/basis는 구체 slot key와 coherence 검사가 없다. 기존 `evidence/research.py:_selection_key`에는 기간 시작/길이가 없고, `deep_research.py:448–483`은 canonical metric별로 다시 고른다. `calculations/equity.py`는 전달된 capex를 빼고 ROIC에 전달된 invested_capital을 사용한다. 단위·기간만 같아도 현금유출 부호/평균잔액/주식 종류 의미가 다르면 결과가 바뀐다.

**수정:** `SlotSpec`과 `MetricDefinition`을 계약에 둔다. SlotSpec에는 metric, exact PeriodKey, statement basis, dimension/currency, share/security basis, actual/forecast, quote/session constraint, required/optional을 포함한다. PeriodKey는 INSTANT와 DURATION을 union으로 분리하고 DURATION의 start/end inclusive 여부를 고정한다(권장: 원본 날짜 양끝 포함, duration_days=end-start+1). fiscal_year/fp는 보조 label이며 기간 identity가 아니다. 경제적 동등성이 확인되지 않은 UNKNOWN을 wildcard로 쓰지 않는다.

MetricDefinition에는 flow/stock/per-share/ratio, 허용 dimension, capex 부호 규약, 총발행/유통/가중평균 주식, 평균 잔액 산식, numerator/denominator 및 변환 방법을 명시한다. 비율의 percent와 fraction도 scale이 다르다. YTD 차분은 동일 시작일/회계·정정 basis와 실제 날짜 관계를 확인하며, 서로 다른 accession이라는 이유만으로 무조건 차단하거나 같은 fy라는 이유만으로 허용하지 않는다. “동일 정정 vintage”는 호환 가능한 restatement basis로 구체화한다. 전년동기 365/366일 차이는 별도 비교 정책 없으면 자동 동등하지 않다. 지원하지 않는 달력/53주 관계는 reason과 함께 보류한다.

`build_financial_set(request, snapshot)`은 완성 metric의 수가 아니라 **계산별 관계**를 검증한다. 일부 개별 fact가 유효해도 같은 기간의 revenue+income 묶음이 없으면 margin은 unavailable다. 재무/13F 자료 기준일은 실제 binding들의 날짜 목록/범위로 보존하고 수집 전체의 max date를 사용하지 않는다.

**필수 테스트:** 같은 end의 Q2/YTD, 서로 다른 FY calendar, annual/TTM, 연결/별도, parent/consolidated net income, END/BASIC/DILUTED shares, segment, capex 부호, percent/fraction, 평균자본 부재, YTD 차분 정상/정정 혼합 실패, permutation 및 동률 충돌. 손계산 fixture에서 최종 값과 정확한 fact ID를 함께 비교한다.

### F05 — fallback 종료 시점과 후보 우선순위가 C03 선택 규칙과 결합되어 있지 않음

영향: C02/C03/C06, R01/R04–07/R12. 공통계약 release 차단.

설계 83행은 출처 우선순위/공개시점으로 선택하고 118행은 요구 품질 달성 시 중단한다. “달성”의 자료형이 없어 first available, metric-name union, 마지막 batch 선택 중 어느 구현도 표면적으로 부합할 수 있다. 기존 `providers/execution.py`는 usable에서 종료하고, `research.py:collect`의 웹 fallback은 웹 batch만 다시 선택한다. 자체 실행에서도 stale→fresh 후보의 실제 호출은 stale 하나였다.

**수정:** `CollectionRequest`는 SelectionRequest, `SourcePlan(version, ordered_stages, coverage_scope)`, 기술적 budget을 가진다. `CoverageDecision`은 coherent selected set 기준 fulfilled/missing/conflicted slot과 미충족 품질 조건을 반환한다. `collect`는 누적 전체 후보를 재평가하고 적격 기존 값을 보존한다. 권장 종료 규칙은 manifest에 명시된 authority/quality stage의 호출을 끝낸 후, 필수 slot과 coherence가 모두 충족되면 종료하는 것이다. 같은 priority stage 내 비교 대상은 모두 확인하여 동률 충돌을 놓치지 않는다. 후속 미조회 source는 NOT_ATTEMPTED로 남기며 모든 공급자 최신성/무충돌을 주장하지 않는다. stage 순위는 selector의 source 우선순위와 같아야 한다.

`ProviderResult.usable`은 호환 전송 상태일 뿐 종료 조건이 아니다. attempt에는 transport success와 accepted slot을 따로 기록한다. 필수 slot 미충족의 all exhausted/budget/not configured를 구분한다. 잘못된 observation 하나는 해당 관측만 reject하고 다음 관측/provider를 계속 처리한다.

**필수 테스트:** stale→valid, partial 서로 다른 기간의 가짜 completeness, partial 동일 기간 보완, 중간 timeout, all exhausted, 빈 SEC nested response, 동순위 conflict, 나쁜 후속 값이 좋은 기존 값을 지우지 않음, 후보 입력 순서와 batch 나누기 변경에 대한 동일 semantic snapshot(같은 source plan/후보 범위에서).

### F06 — 미승인 정책 gate와 계산/보고 소비자의 상태 전파가 빠지면 숫자가 우회 유입됨

영향: C02/C07, R01/R08–11/R13/R17. gate 타입은 계약 release 차단; 소비자 연결은 해당 기능 release 차단.

설계 128/174/216/231–249행은 unavailable, conditional, UNVALIDATED를 서술하지만 C07의 availability enum에는 CONDITIONAL이 없고 calculation/action/report 사이 gate 결과 타입이 없다. 기존 valuation은 naked Decimal과 넓은 evidence_ids 묶음을 받으며 `asset_analysis.py:_persist_result`는 실제 입력 대신 subject/evidence_ids만 저장한다. `reporting/builder.py`는 문장 속 숫자와 계산값의 동등성을 검증하지 않는다. gate를 UI 문구만으로 구현하면 이 경로가 남는다.

**수정:** availability enum은 그대로 두되 독립 `GateDecision(state=ENABLED|CONDITIONAL|DISABLED, purpose, policy_id/version/hash, approval_ref, validation_ref, reasons, prerequisites)`를 추가한다. `DISABLED` 수치 결과는 value=null. 미승인/미검증 투자정책은 DISABLED다. CONDITIONAL은 검증된 입력과 명시적 가정으로 계산은 가능하지만 충족 전제/적용 제한이 남은 경우에만 허용한다. 미승인을 conditional이라는 이름으로 우회하지 않는다. 13F raw feature 설명은 가능하지만 UNVALIDATED aggregate score/매매 반영은 불가다. 지표 n이 없으면 지표값도 unavailable; 명시적 실험 파라미터가 있으면 계산 결과만 조건부 설명하고 신호 승인을 분리한다.

생산 orchestration의 계산 API는 BoundInput/FinancialSet/BarSet만 받는다. 기존 순수 수학 함수는 유지할 수 있으나 validated gateway를 통해서만 보고서·행동 제안에 연결한다. report 숫자 셀은 `NumericBinding(calculation_ref, output_path, currency/unit, display_policy)`로 생성한다. statement-level evidence 묶음은 해당 셀의 입력 증명이 아니다. 해당 input/policy gate 변경 시 그 하위 배수/진입구간/수량/판단을 함께 낮춘다. 가격이 없어도 적격 재무/가치 자체는 살린다.

**필수 테스트:** 모든 정책 absent인 실행에서 임의 n/margin/위험예산/13F weight 미생성, stale price로 PE·buy range 없음, UNVALIDATED feature에서 aggregate/action 없음, 조건부 가정의 표시, binding 값/통화/selection hash 변조 거부, 일부 자료 누락이 독립 지표를 불필요하게 지우지 않음.

### F07 — 공통 타입의 소유 경계와 병렬 시작 조건에 순환 의존 위험이 있음

영향: 설계 §9, C01–C07, R06–09/R12–17. 공통계약 release 차단.

설계 317–327행은 공통 파일 단일 작성자를 정했으나 Bar/Filing13F/FinancialSet/분석 결과 타입 중 무엇이 contracts인지와 “관련 __init__.py”의 범위가 불명확하다. B는 A evaluator conform, A 계약은 B/C payload가 필요하므로 각 팀이 구현 타입을 상호 import하면 병렬 baseline이 깨진다. 기존 `providers/models.py`는 registry를 import한다. 13F capability도 현재 enum에 없다. tasks 상단은 A가 CONTRACT-01, C가 BRIEF-01이라고 확정했으므로 설계의 “나중 지정”을 그대로 적용하면 안 된다.

**수정:** 공통 wire DTO/enum/Protocol/codec/fixture는 `contracts/**` 하나에 둔다. contracts는 stdlib 외 runtime 모듈을 import하지 않는다. provider/normalization/institutional/reporting이 contracts를 소비하며, A의 실행 evaluator와 B/C adapter 구현은 contracts 밖에 둔다. 소유가 중복되는 FinancialFact/Bar/13F DTO를 별도 정의하지 않는다. 13F는 권장 `ProviderCapability.INSTITUTIONAL_HOLDINGS = 'institutional_holdings'`를 A가 registry에 추가한다(요청 모드/스킬 추가 아님). 기존 FUND_HOLDINGS와 의미를 혼합하지 않는다.

CONTRACT-01은 아래 §3 공통 API와 valid/invalid fixture를 export하고, B/C는 아직 A 계산 구현 없이 decode/encode/conformance를 테스트할 수 있어야 한다. A가 registry/factory/common config·exports를 연결하되 B/C 구현 모듈이 아직 없을 때 unconditional import하지 않는다. B/C는 연결 manifest 요청을 인계하고 A가 통합한다. 상세 파일 소유권은 §5에 따른다.

**필수 테스트:** 빈 새 process의 import, B/C 모듈 미존재 상태에서 contracts import 성공, A/B/C fixture 같은 codec roundtrip, enum 문자열·함수 signature 계약 테스트, registry의 미등록/미설정 상태. 계약 commit/hash/version 수신 확인을 각 인계에 기록한다.

### F08 — 개인 pin과 ModeResult 완료의 검증 프로토콜은 후속 구현 전 확정해야 함

영향: C01/C07, R10/R11/R14/R16/R17. 초기 B/C parser 작업 차단 아님; BRIEF/INTEGRATE 활성화 차단.

설계 38/235/255–269행은 같은 state_version을 요구하지만 pin 식별자와 분석에 쓰는 잔액/수량이 같은 read snapshot에서 나온다는 계약은 없다. `RunDatabaseManager.initialize_run_context`는 호출자가 전달한 pin 식별자를 저장할 뿐 projection 데이터의 일관성을 입증하지 않는다. 개인 schema를 바꾸지 않는 방향에서도 읽기 Protocol은 필요하다. 기존 일곱 모드 acceptance는 router/planner만 확인하므로 산출물 완료의 근거가 될 수 없다.

**수정:** contracts에 `PersonalStatePin = NotApplicable | Unavailable(reason) | Pinned(db_instance_id, state_version, portfolio_data_as_of, snapshot_fingerprint)` 및 `PersonalStateReader.read_snapshot() -> PinnedPortfolioSnapshot` Protocol을 둔다. integration adapter는 단일 검증된 read transaction에서 identity/version/projection을 읽고 불변 객체로 돌려준다. 분석 중 DB를 다시 읽어 current state를 혼합하지 않는다. run DB에는 식별자·필요 최소 파생 binding만 기록하고 개인 원장 전체를 복제하지 않는다. schema 변경은 필요 없다. backend 구현 소유자는 A/INTEGRATE-01로 명시한다.

고정 모드별 `RequiredOutputSpec`/step receipt를 선언한다. 필수 handler 미구현은 UNSUPPORTED, 구현은 있지만 자료 부족은 PARTIAL/UNAVAILABLE, 실행 예외는 FAILED다. 모든 가격 unavailable여도 빈 보고서 존재를 COMPLETED 근거로 사용하지 않는다. REPORT_REFRESH는 원 모드 재실행이며 mutation receipt를 replay하지 않는다. UPDATE_THEN_ANALYSIS는 receipt 후 새 pin을 얻고 재시도 idempotency를 유지한다. ActionProposal은 non_posting literal이며 transaction 변환 기능을 제공하지 않는다.

**필수 테스트:** 서로 다른 db_instance의 같은 version 거부, snapshot 읽기 중 합성 동시 변경에서 일관성 보존, absent pin인 단일 분석의 DB 생성/접근 0회, 질문/부정/명령/draft/confirmed composite, refresh 재posting 0회, 일곱 모드 실제 결과·receipt·완료 상태. 개인 데이터 테스트는 후속 구현 환경의 합성 전용으로 수행하며 이번 리뷰에서는 하지 않았다.

## 3. CONTRACT-01에 전달할 최소 API와 저장 매핑

아래 이름은 **제안하는 확정 계약**이며 기존 구현이라고 주장하지 않는다. 각 함수는 typed Result 또는 도메인 오류를 반환한다. malformed provider row는 RowRejected, 프로그래머/계약 오류는 ContractError로 구분한다.

```python
# contracts/**: stdlib-only. All public payloads immutable.
decode_contract(document: str, *, expected_kind: ContractKind) -> ContractObject
encode_contract(value: ContractObject) -> str
semantic_hash(value: ContractObject) -> str

class EligibilityEvaluator(Protocol):
    def evaluate(self, item: NormalizedEvidence, context: RunContext,
                 slot: SlotSpec, policy: EligibilityPolicy) -> EligibilityDecision: ...

select_inputs(request: SelectionRequest, candidates: tuple[NormalizedEvidence, ...],
              context: RunContext, evaluator: EligibilityEvaluator) -> SelectionSnapshot
evaluate_coverage(request: SelectionRequest, snapshot: SelectionSnapshot) -> CoverageDecision
build_financial_set(request: FinancialSetRequest, snapshot: SelectionSnapshot) -> FinancialSet

class ContractStore(Protocol):
    def pin_context(self, context: RunContext) -> ContextRef: ...
    def append_candidates(self, batch: CandidateBatch) -> tuple[EvidenceRef, ...]: ...
    def commit_selection(self, snapshot: SelectionSnapshot, *,
                         expected_revision: int | None) -> SelectionRef: ...
    def load_selection(self, ref: SelectionRef) -> SelectionSnapshot: ...
    def append_calculation(self, record: CalculationRecord) -> CalculationRef: ...

collect(request: CollectionRequest, sources: SourcePlan,
        evaluator: EligibilityEvaluator, store: ContractStore) -> CollectionOutcome
```

evaluator 실행 구현은 A, Protocol/DTO는 공통계약 소유로 분리한다.

핵심 DTO 필수 필드:

| 타입 | 최소 계약 |
|---|---|
| RunContext | run_id, mode, aware cutoff, IANA timezone, runtime/config/contract versions, manifest hash, PersonalStatePin |
| InstrumentKey | issuer/underlying와 listing/security 식별자 분리, market/venue, class/wrapper, quote currency, 검증 resolution ref |
| EvidenceEnvelope | evidence/fact ref, kind, instrument, source identity/locator/fingerprint, raw value/unit, observed/period, AvailabilityTime, retrieved_at, source policy version, payload |
| UnitSpec | dimension, currency 또는 해당 없음, base scale, explicit scale 상태, share/quantity basis, normalization stage/version; commodity mass·contract multiplier는 명시되거나 unsupported |
| EligibilityDecision | decision ref, request/slot/context/policy hash, payload semantic hash, eligible, freshness, reason codes; 외부의 approved bool만 신뢰하지 않음 |
| SelectionRequest | purpose + instrument + 슬롯/기간·기준 + source/quality policy; 전체 canonical request hash |
| SelectionSnapshot | run/request hash, revision, supersedes ref, candidate-set hash, slot별 SELECTED/MISSING/CONFLICT, BoundInput, 제외 사유, coverage, frozen hash |
| BoundInput | normalized value/unit/period/basis + 정확한 evidence/fact refs + transformation refs + eligibility ref + selection ref/hash |
| CalculationRecord | formula/version, role별 BoundInput/선행 calculation, assumption ref, as_of/config hash, Decimal context, outputs, availability/gate, 실패 사유/표시 반올림 정책 |
| Assumption | 값/단위/대상기간, 사실과 구분된 origin(USER/ANALYST/SOURCE), locator 또는 입력 ref, provenance/approval 상태, scenario/model 적용 범위 |
| CollectionOutcome | snapshot ref, attempt receipts, missing/conflicted slots, stop_reason, availability; selected ProviderResult 하나로 대체하지 않음 |

semantic hash는 run-local UUID/retrieved_at/실행 시작시각을 제외한 정규화된 의미 payload와 정책·원본 identity를 대상으로 한다. 공개버전·기간·단위는 포함한다. 별도로 raw content hash를 보존한다. calculation 재실행 비교는 참조 UUID 대신 대응 semantic hash를 사용한다. Decimal context를 적용하는 연산과 hash용 textual canonicalization을 혼동하지 않는다.

기존 schema만 사용하는 권장 매핑:

| 기존 위치 | 저장 내용/제약 |
|---|---|
| run_metadata.metadata_json | 보호 namespace `contract_context`, `contract_state.active_selections[request_hash]`; clock/context는 불변, active ref 변경은 revision CAS |
| evidence.metadata_json | fact/quote/bar/holding별 typed payload. 원문 대형 공시 전체 금지. provider raw metadata와 trusted contract namespace 분리 |
| evidence의 `evidence_type='contract_selection'` 행 | immutable SelectionSnapshot의 typed JSON. 일반 raw-evidence 수집/선택·보고 통계에서는 제외하는 명시적 query |
| market/financial observations metadata_json | typed payload/ref와 evidence_id; NUMERIC 값은 projection. 13F는 evidence payload로 표현 가능하며 market row를 가짜로 만들지 않음 |
| calculations.inputs_json/result_json | versioned CalculationRecord 입력/출력. 계산 ref의 존재·같은 run·단위/기간·snapshot hash를 facade가 확인 |
| provider_states.metadata_json | ordered attempt receipt, accepted/rejected slots, bounded retries, 종료 원인; credential/query token 제거 |
| task_states/report_sections metadata_json | 실행 receipt/요구 output 충족 및 binding. COMPLETED와 자료 availability는 별개 |

`evidence.selection_state`/`observation_selections`는 기존 조회 호환 projection일 뿐 공통 선택의 authoritative 원장이 아니다. 같은 evidence가 purpose마다 다르게 선택될 수 있어 단일 SELECTED 열로 표현할 수 없다. 새 계산/보고는 반드시 snapshot ref를 읽는다. financial selection을 market FK에 억지로 넣지 않는다. append_calculation은 이미 고정된 snapshot 참조만 허용한다. 새 selection을 만들더라도 기존 계산의 과거 snapshot은 변경하지 않고, 새 현재 보고서는 사용할 snapshot을 명시한다.

이 매핑은 run manager facade의 원자성·복구 검증이 전제다. 대규모 Bar/13F의 처리시간/크기 한계는 실제 fixture로 측정하고 기록한다. 저장 한계 초과를 silent truncate하지 않는다. 필요할 때만 이후 run-only migration을 별도 검토한다. 이번 계약 통과를 임의의 성능 목표나 무제한 데이터 지원으로 표현하지 않는다.

권장 reason code 최소 집합: CONTRACT_VERSION_UNSUPPORTED, INVALID_NUMBER, INVALID_SCALE, UNIT_CONFLICT, CURRENCY_CONFLICT, IDENTITY_UNRESOLVED, PERIOD_MISMATCH, BASIS_MISMATCH, PUBLIC_TIME_UNKNOWN, NOT_PUBLIC_AT_CUTOFF, OBSERVATION_AFTER_CUTOFF, SUPERSEDED, UNRESOLVED_CONFLICT, POLICY_UNAPPROVED, VALIDATION_REQUIRED, INSUFFICIENT_COVERAGE, NOT_CONFIGURED, BUDGET_EXHAUSTED, CANDIDATES_EXHAUSTED. 한국어 문구와 기계 코드는 분리한다.

## 4. R01–R17 구현 계약의 완료/제한 판정

| REQ | 구현자가 제출할 증거 | 정책/외부 검증 부족 시 |
|---|---|---|
| R01 | structured/web/all-failed에서 selected binding부터 PE/행동표까지 stale 배제; calendar 검증 | 지연/종가 policy 없음은 현재가 계산 unavailable |
| R02 | exact period/coherence, YTD/TTM·정정, permutation, 실제 사용 fact 날짜 | 추정 annual/비교기간 금지 |
| R03 | codec+dimension/scale/currency/FX 방향·시각 경계와 계산값 | 근거 없는 FX/scale 보완 금지 |
| R04 | 실제 구조의 합성 nested fact→FinancialSet→계산 binding; accession metadata | unsupported tag/basis/version을 성공 지표에 포함하지 않음 |
| R05 | 누적 후보·coherent coverage·stage/종료 원인; 정상 값 보존 | first AVAILABLE는 완료 아님 |
| R06 | 목표 시장별 실제 페이지 접근·필드/시각 성공 또는 제한 기록과 대체 fixture | live 미검증은 기능 제한/미완료 명시 |
| R07 | BarSet 정렬/세션/구멍/분할·vintage/미완성 검증 | 캘린더/수정 basis 미확인은 rolling 입력 제외 |
| R08 | 명시 파라미터의 손계산·seed·prefix invariance 및 report binding | n 없음은 지표 unavailable, 신호 미승인은 gate DISABLED |
| R09 | 모델별 가정 origin·FCFF/FCFE·net debt·shares·scenario/grid lineage | 출처/입력 없는 시나리오 범위 발명 금지 |
| R10 | 판단/가격조건의 gate 전파, 누락 시 대기, 안전마진 provenance | 정책 없으면 숫자 진입구간 unavailable |
| R11 | 같은 read snapshot, 현금/FX/위험/거래단위/tranche 합, non-posting | 개인 정책/처분가능 수량 없으면 정밀 규모 unavailable |
| R12 | 실제 source schema vintage, 정정 타입/scope·cutoff·identity·SH/PRN·absence | 원문/XSD 미검증은 parsing 지원 범위 제한 |
| R13 | 사전등록·PIT·baseline·기간 외/coverage/비용/누출 검증 artifact | feature 후보·gate 구현은 가능; 실증 없는 가중치 채택은 미완료 |
| R14 | 7개 execute 결과물·필수 receipt, composite/draft/idempotency/refresh | handler 없는 모드는 UNSUPPORTED, no-op 성공 금지 |
| R15 | 같은 interpreter 설치/wheel/config/8 skills/UI mirror/allowlist | 문서 변경만으로 설치 완료 주장 금지 |
| R16 | 최종 통합 SHA의 실제 수집→브리핑 및 회귀·별도 새 세션 검증 | 이전 287개 통과/본 설계 리뷰로 대체 금지 |
| R17 | 5단계 한국어 출력, 숫자 binding·날짜/통화·주요 불확실성 일치 | 미승인 값은 빈칸/0/추천 수치로 채우지 않음 |

gate가 정상 동작한다는 것은 제한을 정직하게 구현했다는 뜻이다. R13의 실증이나 R06의 live 확인까지 완료했다는 뜻은 아니다. 전체 완료 보고에는 `implemented`, `fixture_verified`, `live_verified`, `policy_enabled`를 별도 필드로 기록하는 편이 적합하다.

## 5. 병렬 소유권·의존성 수정안

1. 총괄: 이 검토의 F01–F08을 기술 결정으로 반영한 계약 버전/문서 diff를 확정하고 A/B/C에 전달한다. 추가 사용자 투자정책 승인을 만들어 요구하지 않는다. 총괄만 commit/통합한다.
2. A/CONTRACT-01: `contracts/**`, `providers/models.py/registry.py/factory.py`, `evidence/manager.py`, 공통 config/invariants 및 **기존 공통 package exports**. 신규 `tests/contracts/**`와 공통 fixture도 A 단독 소유. 기존 run migration·개인 schema는 그대로 둔다.
3. 계약 gate: stdlib-only import, strict DTO/codec, F01–F05 및 gate DTO fixture, run facade atomic roundtrip 테스트. 통과 후 총괄의 새 commit을 B/C가 수신 확인한다. B/C는 그 전 요구 분석/공개 원문 구조 확인 같은 독립 준비만 가능하다.
4. A/IMPL-A: evaluator/selector/coherence, provider execution/adapters, research/deep_research, normalization. A/ANALYSIS-09는 equity/valuation/common. contracts에 순환 import를 넣지 않는다.
5. B: market_quotes/ohlcv, web_research, calculations/technical, B 전용 테스트. 신규 전용 package의 exports는 B, 기존 공통 exports 변경은 A에게 요청. R15 PACKAGE는 통합 API freeze 후 수행한다.
6. C: sec_13f, institutional normalize/compare/scoring/validation, C 전용 테스트. common 13F DTO를 재정의하지 않는다. 이후 decisions/reporting/BRIEF는 A/B/C의 typed 결과 fixture와 gate 계약에 의존한다. 경로는 `decisions/`로 고정해 strategy와 중복 생성하지 않는다.
7. A/INTEGRATE: execution/routing/pipelines/cli/asset_analysis와 read-only personal snapshot adapter. deep_research는 같은 A 내 작업 단계 인수 기록을 남긴다. C reporting이 소비하는 common numeric binding/ModeResult는 초기에 contracts에 두거나 계약 freeze 전에 signature를 명시한다.
8. 후속 REVIEW-CODE-01은 구현을 직접 검토하고 담당 Gemini가 수정한다. VERIFY-01은 다른 새 세션에서 최종 SHA를 테스트한다. B/C에 전달된 baseline이 첫 SHA로 남지 않도록 handoff에 실제 계약 commit을 기록한다.

**차단 해제 기준:** F01–F07의 타입/저장/선택 계약이 구현·검증된 뒤 B/C 종속 작업을 시작한다. F06 소비자 연결과 F08은 BRIEF/INTEGRATE release 전 해결한다. 해당 기능 미구현을 gate로 숨겨 전체 완료를 선언하면 차단 해제가 아니다.

## 6. 이번 세션에서 실제 실행한 검증

인터프리터: `C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe`, 직접 출력 버전 Python 3.14.6. `-X utf8 -B -`로 표준입력 runner를 실행해 소스/bytecode 파일을 만들지 않았다.

기존 테스트 16개: **OK, failures 0, errors 0**.

- tests.unit.test_phase4_providers — 6개
- tests.unit.test_phase4_freshness_web — 7개
- tests.acceptance.test_phase8_request_modes — 3개

runner는 `sqlite3.connect`와 `socket.create_connection`을 실패 함수로 교체했고, provider/web는 테스트의 주입 transport만 사용했다. 테스트 16개가 DB/live/일곱 모드 실행을 검증했다는 뜻은 아니다.

추가 메모리 합성 probe의 실제 출력:

```text
future_publication_freshness= FRESH
decimal_nan_is_finite= False
invalid_scale= invalid result= (Decimal('10'), None)
invalid_scale= -1000 result= (Decimal('10'), None)
selected_after_two_batches= 2
fallback_calls= ['stale']
```

probe 입력은 TEST/USD 100, cutoff 2026-09-23 09:00 UTC, observed 08:59/publication 다음날, 잘못된 unit_scale 두 가지, in-memory evidence manager 두 batch, stale/fresh 가짜 adapter다. 숫자는 오류 재현용 합성 값이며 투자정책 제안이 아니다. DB manager를 실제 생성하지 않았고, 네트워크 호출도 없었다.

미실행: 전체 테스트 재실행, 새 계약 코드 테스트(아직 없음), 실제 run JSON/SQLite atomic rollback, personal snapshot 동시성·DB 불변 테스트, SEC/13F 실제 parsing, live 시세, OHLCV/지표/가치평가/브리핑 신규 통합, wheel/install/UI mirror, Gemini 실행, 투자정책/13F 가중치 실증. 이러한 항목의 통과를 이 보고서에서 주장하지 않는다.
