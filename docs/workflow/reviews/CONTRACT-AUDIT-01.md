# CONTRACT-AUDIT-01 — 고정 계약 스냅샷 인수검토

검토일: 2026-09-23. **판정: CHANGES_REQUIRED / 계약 인수 보류.** P0는 확인하지 못했다. 알려진 import/API 불일치와 별개로 아래 **추가 P1 7건**을 확인했다. 다중종목 scope 문제는 총괄이 CONTRACT-FIX-02에서 수정 중이라고 확인하여 별도 추적한다.

검토 폴더: `C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit`.
직접 확인한 전체 SHA: `73d376e32437bf78f8534d040c68db106e59acb7`.
계약 wire 버전: `0.2`. 기준 요구/설계: REQ-2026-09-23-v1 / DESIGN-2026-09-23-v0.1 / 선행 REVIEW-DESIGN-01 F01–F07.

현재 root나 Gemini A의 수정 중인 폴더는 읽지 않았다. 아래 코드 경로·행 번호는 모두 이 고정 폴더의 `runtime/investment_stack/` 기준이다. 새 코드검토·최종 VERIFY를 대체하지 않는 계약 인수검토다.

## 1. 검증 범위

- AGENTS.md, contracts/**, evidence/manager.py, providers/contract_adapters.py, 관련 provider exports 및 신규 contract 테스트의 관련 부분, CONTRACT-FIX-01 인계를 직접 읽었다.
- Python 3.14.6으로 `-X utf8 -B -` 표준입력 합성 probe를 실행했다. `sqlite3.connect`와 `socket.create_connection`을 실패 함수로 교체했다. 메모리 DTO/codec/helper/adapter만 검사했으며 DB를 만들거나 열지 않았다. 네트워크·개인 DB 접근 없음.
- `contracts` 단독 import는 성공했다. manager import는 알려진 `MAX_PAYLOAD_BYTES` ImportError로 실패했다. 이를 우회하는 monkeypatch/소스 수정은 하지 않았다. 실제 SQLite transaction/CAS/rollback/reopen 검증은 **미실행**이다.
- 총괄 보고의 37 tests 중 2 failures/10 errors는 이번 실행 결과가 아니다. 알려진 nested PublicAvailability plain/envelope 불일치와 stale test API를 다시 전체 테스트로 재현하는 작업은 생략했다.
- adapter probe 중 ProviderObservation roundtrip은 `observation_id` 미지원 TypeError로 중단됐다. 그 뒤의 Bar probe는 별도 정상 실행했다. confirmation roundtrip 성공을 주장하지 않는다.

## 2. 추가 P1과 수정·인수 조건

### CA01 — evidence 존재 확인은 값의 출처 검증이 아니다

**근거: 정적.** `evidence/manager.py:383–407`의 add_contract_evidence는 decode_envelope로 봉투 형태만 확인한다. typed payload를 decode하지 않고, 호출자가 지정한 content_hash도 그대로 받는다. `914–939`의 snapshot 검증은 evidence/market observation의 존재와 run_id만 본다. source payload의 값·단위·종목·기간·공개시점과 BoundSlotInput의 일치, eligibility/input_fingerprint, observation.evidence_id 연결은 검사하지 않는다. 테스트의 setUp도 값 없는 `evidence_type='test'` 행을 seed한 뒤 임의 숫자 binding 저장 성공을 기대한다.

**영향:** 같은 run의 무관한 evidence ID만 알면 임의 금액/통화/기간을 붙인 snapshot이 구조상 통과한다. 해시 재계산이나 ID 존재 확인만 강화해도 출처 무결성은 해결되지 않는다.

**수정 계약:** source registry가 신뢰한 adapter/normalizer 경계에서 raw source locator/content hash, source/mapping/normalization version, raw→canonical transformation, instrument/period/basis/unit/currency/public availability를 담은 canonical evidence payload를 만든다. add_contract_evidence는 expected kind의 typed decode와 해당 payload의 정상화 상태를 검증해야 한다. 임의 metadata/self-approved/source_tier 값으로 trusted 상태를 부여하지 않는다. snapshot commit은 이 **저장된 trusted canonical payload**를 읽고 BoundInput의 전체 의미와 비교한다. 변환된 값이면 기존 변환 CalculationRecord의 입력·출력 참조를 따라 일치를 검증한다. caller가 붙인 fingerprint 문자열이 있다는 사실만으로 통과시키지 않는다. observation_id를 받으면 같은 run뿐 아니라 evidence_id 연결도 같아야 한다.

**필수 반례:** 값 없는 evidence에 가격 100 binding, evidence USD→binding JPY, A종목 evidence→B 요청, 관측 O의 evidence가 E1인데 binding은 E2, 미래공개 evidence, invalid scale payload, typed kind는 맞고 필수 payload가 빈 경우를 모두 commit 전에 거부. 정상 변환 binding은 허용. 실패 시 snapshot/active ref/calculation projection 변화 0건.

### CA02 — 계산이 실제로 참조한 snapshot과 전체 binding을 비교하지 않는다

**근거: 정적.** `manager.py:957–972`는 bundled calculation의 snapshot hash가 과거 history에 있으면 허용하면서 입력 검사는 현재 snapshot_slots_by_id에 한다. 따라서 과거 hash에 현재 입력을 붙이는 검사가 된다. `970` 및 standalone 경로 `1185`는 evidence_id와 값만 비교하여 unit/currency/availability/fingerprint/eligibility/선행 계산을 제외한다. 현재는 값 필드도 DTO의 canonical_value 대신 bound_value를 참조하는 API 오류가 있어 이 경로의 실행 성공은 미검증이다.

**수정 계약:** bundled/standalone 모두 하나의 공통 validator를 사용한다. calculation.selection_snapshot_hash로 정확한 immutable snapshot을 load한 뒤 각 binding의 canonical representation 전체(또는 trusted 의미 hash와 참조 구조)를 비교한다. slot ID 중복을 거부하고 formula가 요구하는 역할/입력의 누락을 검사한다. 선행 calculation/assumption evidence도 같은 run·실제 참조·순환 없음·cutoff/정책 호환을 확인한다. 단순 필드 이름 변경만으로 완료 처리하지 않는다.

**필수 반례:** 같은 value/evidence에 JPY만 변경, period/eligibility/transform만 변경, snapshot S1=100/S2=200에서 calc가 S1 hash+S2 input, 다른 run 선행 calc, 중복 slot을 거부. S1을 명시한 정상 과거 계산은 S2 commit 이후에도 정확한 S1 입력으로 재생 가능해야 한다.

### CA03 — strict decoder가 문자열 bool·unknown enum·잘못된 nested kind를 승인한다

**근거: 실제 메모리 실행 + 정적.** `calculation.py:278`의 bool('false')는 True다. 이를 decode한 assumption으로 CALCULATED 결과 생성까지 성공했다. `slots.py:608`도 is_complete='false'를 True로 바꾸며 missing_slots가 있어도 완료다. `slots.py:461`은 duration_days=True를 int 1로 변환해 __post_init__의 bool 차단을 우회한다. SlotSpec dimension/purpose='ALIEN'과 날짜 'bad'도 통과했다. `market.py:220` 등은 nested decode에 expected_kind를 주지 않으며 MarketQuote.public_availability에 GateDecision envelope를 넣어도 실제 GateDecision 객체로 decode됐다. 이는 알려진 plain/envelope roundtrip 실패와 별개의 타입 혼동이다.

**수정 계약:** wire scalar는 coercion 전에 정확한 type을 검사한다. bool 필드는 실제 bool만, int 필드는 bool 제외 int만 받는다. enum은 직접 생성과 decode 양쪽에서 닫힌 집합을 검증한다. 모든 nested field는 expected_kind와 Python DTO 타입을 확인한다. date는 date parser로 검증한다. SelectionRequest/CoverageDecision도 unknown keys를 거부하고 완료 상태는 required/fulfilled/missing/conflicted 불변식에서 산출한다. json duplicate keys/non-finite constants도 strict decode 정책으로 명시한다.

**필수 반례:** 'false'/'0'/0/1/null 각각의 승인·완료 bool, bool/소수 duration/revision, unknown enum, PublicAvailability 자리에 GateDecision/RunContext, unknown CoverageDecision key, fulfilled와 missing의 중복 및 missing 있는 is_complete=True. 전부 거부하거나 올바른 false/partial 상태로 산출해야 한다.

### CA04 — gate가 계산과 연결되지 않고 CONDITIONAL로 미승인을 우회할 수 있다

**근거: 실제 메모리 실행 + 정적.** `calculation.py:85–96`은 ENABLED만 approval_ref를 요구한다. CONDITIONAL은 approval/validation/prerequisites가 전부 없어도 생성된다. CalculationRecord에는 GateDecision 참조가 없어서 disabled gate와 CALCULATED 결과의 관계를 검증할 방법이 없다. 미승인 assumption은 조건부 계산을 허용하지만 모델 설명용 가정과 채택 금지인 투자정책/13F 가중치를 구분하지 않는다. UNAVAILABLE 계산도 result_payload={'buy_price':'100'}와 정상 lineage hash를 가질 수 있었다(149행은 result_numeric만 확인).

**수정 계약:** formula/purpose별로 정책이 필요한지와 필요한 gate를 계약에 선언하고 CalculationRecord가 해당 gate ref/hash를 포함하게 한다. gate approval/validation은 trusted 설정/검증 artifact에서 확인한다. 일반 명시적 analyst scenario는 조건부 설명 가능하지만 미승인 신호·안전마진·위험예산·13F aggregate는 DISABLED/value unavailable이어야 한다. CONDITIONAL은 그 용도에서 허용된 조건 및 명시적 가정·전제가 있어야 한다. numeric output schema를 typed화해 status/gate를 결과의 모든 계산 가능한 numeric field에 적용한다. arbitrary payload의 숫자를 보고서가 binding 없이 소비하지 못하게 한다.

**필수 반례:** disabled/unapproved policy+CALCULATED, unvalidated 13F weight+CONDITIONAL, validation_ref 없는 검증필수 gate, required gate 누락, UNAVAILABLE의 action numeric payload. 반면 승인된 정책을 요구하지 않는 단순 산술/명시적 scenario는 적절한 상태로 계속 가능해야 한다.

### CA05 — '정규화/정합 집합' 타입이 기간·통화·정규화 오류를 보장하지 않는다

**근거: 실제 메모리 실행 + 정적.** `financial.py:96–119`는 유한 숫자/양수 scale/문자열 기간 순서만 검사한다. `ScaleStatus.INVALID`, raw 2×scale 1,000,000인데 normalized 999, raw unit USD million/currency JPY, DURATION start=None/end='not-a-date'인 fact 생성이 성공했다. `FinancialSet.create:133–162`는 instrument만 검사하여 USD/JPY 및 ANNUAL/QUARTER 혼합을 covered_metrics로 표시한다. `slots.py:139`는 candidate instrument가 None이면 mismatch를 생략한다. `market.py:148–193`은 BarSet interval을 검증하지 않아 1d set에 1h bar가 들어갔다.

**범위 구분:** invalid raw fact 생성·보존 자체는 결함이 아니다. 이 타입을 raw collection으로 쓰는 것도 가능하다. 차단 문제는 raw/normalized/eligible 상태가 분리되지 않은 채 “coherent, validated” FinancialSet의 covered_metrics에 invalid revenue가 포함되고, downstream이 이것을 필수 입력 충족으로 사용할 수 있다는 점이다. 정상 다른 metric은 부분 결과로 계속 허용해야 한다. 여러 기간·통화를 가진 원자료 collection 자체를 금지하지 않는다.

**수정 계약:** raw candidate와 계산 적격 normalized DTO를 구분한다. invalid/unknown raw 자료는 보존 가능하지만 normalized fact/BoundInput의 검증된 상태를 가져서는 안 된다. normalization formula/ref를 검증하고 raw unit/scale/currency/dimension 관계를 확인한다. INSTANT/DURATION의 실제 날짜·일수 불변식과 SlotSpec의 required identity를 강제한다. FinancialSet이 자료 collection이라면 validated라는 의미와 coverage 완료를 제거하고, 계산용 coherent subset은 별도 request/validator로 생성한다. 여러 기간을 보유하는 것 자체를 금지하는 대신 동일 ratio/성장/TTM 계산이 요구하는 관계를 검증한다. BarSet은 interval 일치, 완료·cutoff·연속 구간·adjustment basis의 검증 receipt를 갖거나 미검증 collection으로 명시한다.

**필수 반례:** 위 합성 fact, identity=None, 같은 end의 quarter/YTD, 통화 혼합 margin, annual/TTM 섞임, 잘못된 duration, 1h→1d 및 미완성 rolling window. 정당한 비교기/당기 자료 집합은 보존하면서 계산별 유효 부분집합만 소비해야 한다.

### CA06 — 재개/read 경로가 손상·미지원 저장 상태를 fail-closed로 처리하지 않는다

**근거: storage helper 실제 실행, manager 경로 정적.** `storage.py:48–79`는 schema_version='999'를 그대로 반환하고 `_contract_storage_v2: null`을 신규 빈 ledger로 바꾼다. latest_revision=10/history=[]/active missing 조합도 extract 단계에서 통과했다. `manager.py:1074–1112`의 read는 전체 chain/counter/run/scope 참조를 검증하지 않고 envelope가 빠진 history를 건너뛰거나 잘못된 active ref에서 None/마지막 history로 fallback한다. `1247–1299`의 integrity 검사도 latest_revision/latest_snapshot_hash와 tail 일치, active key와 대상 scope 일치, snapshot.run_id 및 calculation full binding을 확인하지 않는다. 단순 helper 결과와 실제 DB 재개는 구분해야 하며 후자는 미검증이다.

**수정 계약:** 처음 namespace가 전혀 없는 정상 legacy run과 namespace가 존재하지만 null/불완전한 경우를 구분한다. exact storage schema version·필수 필드·typed entry·counter/hash chain·active scope·run/context·calc 참조와 CA01/CA02 binding 무결성을 검증하는 공통 validator를 open/read/commit에 적용한다. 손상 pointer에서 history fallback으로 성공하지 말고 CorruptedStorageError를 반환한다. 정상 신규 run의 빈 상태만 허용한다.

**필수 반례:** unsupported version, null namespace, latest counter/tail 불일치, 다른 purpose/request를 가리키는 active pointer, 없는 envelope, 외부 run snapshot, stale/mutated calculation binding. 저장 후 새 manager/process로 다시 읽어 같은 결과가 나오는지, 실패 후 원장이 그대로인지 실제 임시 run DB에서 검사해야 한다.

### CA07 — 호환 adapter/13F codec이 단위·공개시점·보유 의미를 잃는다

**근거: 실제 메모리 실행 + 정적.** `providers/contract_adapters.py:18–63`은 fact.normalized_value를 fact.raw_unit과 함께 내보낸다. raw 2 USD million → normalized 2,000,000이 `value='2000000', unit='USD million'`로 출력됐다. period_end는 metadata에 없고 date-only 값이 observed_at으로 들어간다. `103–139`의 Bar close 값 단위는 volume_unit이므로 실제 SHARES였다. `144–172` holding 변환은 quantity_type을 누락해 PRN이 소실된다. DATE_INTERVAL의 bounds/source timezone 및 원 evidence linkage도 단순 projection에 충분히 보존되지 않는다.

`contracts/institutional.py:88/248`은 source vintage 근거 없이 value_scale=1000을 기본값으로 넣는다. 이 값이 어느 실제 filing에 적합한지는 이번에 외부 확인하지 않았으며, 문제는 **명시적 schema/vintage 근거 없이 기본값이 생긴다는 것**이다. 210–251행 Holding13F decoder는 허용 key인 voting_sole/shared/none을 생성자에 전달하지 않아 voting_sole=1이 roundtrip 후 None이 됐다. ProviderObservation decoder는 confirmation/event_cluster/relevance를 전달하지 않는 정적 공백도 있다. 다만 그 decoder는 현재 observation_id TypeError로 먼저 실패하므로 confirmation 소실의 성공 실행은 미검증이다.

**수정 계약:** 기존 observation은 표시 projection으로만 쓰거나, normalized 값에는 canonical unit+normalization stage를 붙인다. raw 값/단위는 별도로 보존해 이중 scale 적용이 불가능해야 한다. typed payload envelope/ref를 유지하고 evidence_id·기간·공개구간·정정/quantity basis를 손실 없이 전달한다. typed→legacy→typed 복원 보장을 하지 않는 projection은 계산 진입점으로 받지 않는다. 13F scale은 검증된 source schema mapping의 필수 입력이고 모르면 unavailable이다. PRN/SH·put/call·클래스·공시 참조 및 voting 필드는 정확히 왕복 보존한다.

**필수 반례:** million fact가 legacy 경계를 지나도 base value 유지, Bar close 단위 money/share 유지, filed-only interval 보존, SH/PRN 구분, value_scale 누락, 모든 voting field roundtrip, NEWS_REPORTED/UNVERIFIED confirmation 보존. raw source tier를 adapter가 근거 없이 1로 승격하지 않는지도 확인한다.

## 3. 이미 수정 중인 scope 문제와 F01–F07 판정

기준 SHA의 `manager.py:1060`은 active_selections[purpose]이며 fetch API도 purpose만 받는다. SelectedInputSet에 instrument/request/context hash가 없다. 동일 run의 A/B종목 CURRENT_PRICE 또는 서로 다른 기간 요청이 덮어써진다. 총괄이 CONTRACT-FIX-02에 이미 포함했다고 회신했으므로 새 발견 수에는 넣지 않았다. 새 snapshot에는 full request hash와 instrument/period/basis/policy/context가 있어야 하고 read/CAS/active scope가 이를 함께 사용해야 한다. **수정 중인 새 SHA는 이번에 검증하지 않았다.**

| 선행 항목 | 이번 판정 |
|---|---|
| F01 strict codec | finite Decimal/outer kind/version 검사 개선. CA03/CA07로 불완전; semantic_hash도 purpose/public time/fingerprint 변화에 동일해 의미 검증에 사용 불가 |
| F02 atomic storage | 하나의 mutation transaction/CAS 구조는 추가됨. import blocker로 실행 미검증; CA01/CA02/CA06 및 scope 미해결 |
| F03 공개시점 | EXACT locator, UNKNOWN false, local-date factory의 DST 설계 개선. wrong nested type 및 adapter loss로 end-to-end 보장 없음; 정정 선택은 이번 인수 범위에서 검증되지 않음 |
| F04 coherent slots | 일부 None 제약 매칭 추가. identity None·기간/단위·normalized state/FinancialSet coherence는 CA05 미해결 |
| F05 fallback coverage | request/coverage DTO 존재. CA03의 거짓 완료 가능. 실제 coherent evaluator/collect 연결·종료 규칙은 미검증 |
| F06 gate/binding | gate/status 타입 추가. CA02/CA04로 정책/계산/출력 경계 미해결 |
| F07 병렬 계약 | contracts 단독 import 성공 및 provider adapter 외부 배치 확인. 저장/typed adapter acceptance가 깨져 B/C 계약 baseline 승인 불가 |

`SelectedInputSet.semantic_hash()`는 슬롯 ID/값/단위/통화만 포함한다. 실제 probe에서 purpose·public_available_at·input_fingerprint를 바꿔도 같았다. 이를 가격/재무 request 재사용 또는 eligibility 동일성 증명에 쓰지 않는다. source/run-local ID를 제외하더라도 instrument/request/period/basis/공개버전·policy는 의미 해시에 들어가야 한다.

## 4. 실제 합성 실행 결과

모든 숫자·종목·정책 ID는 TEST/fixture 합성 입력이다. 다음은 검사 출력이며 통과한 회귀 테스트 수를 뜻하지 않는다.

```text
contract_import= 0.2
manager_import= ImportError: MAX_PAYLOAD_BYTES
string_false_approval= True calculation= CALCULATED
coverage_false_string= True missing= ('price',)
conditional_gate_approval= None validation= None prerequisites= ()
wrong_nested_availability_type= GateDecision
candidate_missing_identity_matches= (True, None)
invalid_slot_accepted= ALIEN 1 bad
financial_invalid_mixed_accepted= ('operating_income', 'revenue') ['USD', 'JPY']
holding_default_scale= 1000 voting_roundtrip= 1 None
unknown_storage_version= 999
null_storage_resets= 0
different_purpose_time_fingerprint_same_semantic_hash= True
unavailable_numeric_payload= {'buy_price': '100'} lineage_ok= True
fact_observation= 2000000 USD million 2025-12-31 period_end_in_metadata= None raw_value= None type= FINANCIAL_FACT
holding_PRN_metadata_quantity_type= None public_availability= None
ProviderObservation roundtrip: TypeError unexpected keyword argument 'observation_id'
barset_interval= 1d bar_interval= 1h complete= False
bar_close_unit= SHARES
```

최소 재현 형태:

```python
# c = investment_stack.contracts
a = c.decode_contract(c.encode_envelope('CalculationAssumption', {
    'assumption_id': 'a', 'name': 'unapproved', 'value': '1',
    'is_approved': 'false'}))
# a.is_approved == True; CALCULATED create가 허용됨

gate = c.GateDecision('g', 'TRADING', 'unapproved', '1', 'hash', 'CONDITIONAL')
# quote payload의 public_availability를 encode_envelope('GateDecision', gate)로 설정
# decode_contract(... expected_kind='MarketQuote') 결과의 public_availability가 GateDecision

spec = c.SlotSpec('s', 'FINANCIAL_CALC', 'TEST', 'revenue', 'MONEY', 'USD')
spec.matches_candidate(candidate_currency='USD', candidate_dimension='MONEY')
# instrument 미제공인데 (True, None)
```

## 5. 인수 재검증 요청

**B/C에 안정된 DTO를 전달하기 전 공통계약 인수 조건:**

1. CA03의 strict scalar/enum/nested type 및 정확한 roundtrip, CA07의 단위·13F quantity/voting 보존과 explicit scale, raw/normalized/eligible 상태와 요청 scope의 닫힌 타입을 먼저 확정한다. 모든 invalid raw 자료를 삭제/거부하라는 요구가 아니다.
2. CA01/CA02/CA06의 저장·재개 validator를 공통 facade에 구현하고, trusted test normalizer가 생성한 canonical payload를 이용해 임시 run DB write→reopen→read→calculation 및 거부/rollback 테스트를 통과한다. caller가 임의 생성한 normalized 숫자+fingerprint를 trusted evidence로 받으면 안 된다. 구현상 trusted normalizer의 위치/호출 경로를 고정하는 것으로 충분하며 불필요한 인증 서명 체계를 만들 필요는 없다.
3. gate→calculation/output 참조와 scope/context/기간/통화/공개버전의 binding 필드를 확정한다. 아직 evaluator가 없는 기능은 eligibility unknown/ineligible 및 unavailable로 닫힌다. 이러한 상태를 codec/store가 승격하지 않는 공통 conformance fixture가 필요하다.
4. 알려진 import/API 오류를 해소하고 위 계약 테스트가 통과한 **새 SHA**를 총괄이 전달한다. B/C는 그 DTO와 normalizer/provider Protocol에 맞춰 구현을 시작할 수 있다. 기존 73d376e는 이 조건을 만족하지 않는다.

**IMPL-A 이후 evaluator/통합 인수 조건:** source별 재무 정규화 mapping, 정정 vintage 선택, 목적별 공개시점/freshness, 실제 기간 coherence/YTD/TTM, 누적 fallback 종료 판단, 최종 계산/보고 gate 적용은 A와 후속 통합의 구현 업무다. B의 Bar calendar/완료·조정 검증과 C의 공시 정정/원문 단위·보유 비교도 각각 후속 담당이다. 이 알고리즘들이 모두 완성돼야 B/C의 parser 코딩을 시작할 필요는 없다. 다만 공통 타입·저장이 “미검증”과 “적격”을 명확히 구분하고, 알고리즘 구현 전에는 미검증 값으로 selection/calculation을 성공시키지 않는 경계가 먼저 있어야 한다.

saved probe의 `COMMON_SET_VS_EVALUATOR`는 현재 FinancialSet이 validated collection/covered_metrics라고 표시하는 API에 대한 회귀다. raw collection과 validated set을 명시적으로 분리하는 설계를 채택하면 이 probe도 새 validator 입력에 옮겨야 하며, raw object 생성 허용 자체를 실패로 취급하지 않는다. 공통 DTO 변경 때문에 probe가 BLOCKED가 되면 새 실제 API로 조정 후 의미상 검사를 다시 수행한다.

우선 CA03의 승인 bool/type confusion, CA01/CA02의 trusted evidence→binding 검증, CA06의 read/reopen fail-closed를 고친다. scope 수정과 CA04–CA07도 공통계약 또는 명시적 미지원 gate로 닫아야 한다. B/C에 잘못된 normalized/validated 타입을 안정 계약으로 배포하지 않는다.

수정 후 **실제 새 commit**에서 정상 import를 전제로 임시 run DB의 write→새 manager reopen→read→calculation 경로와 부정 사례를 실행한다. project_compatible True/False 모두 같은 검증을 적용하고, 실패 중간 주입에서 atomic rollback을 확인한다. 단순 해시 문자열 확인, 필드 rename, happy-path roundtrip 통과로 CA01–CA06을 종료하지 않는다.

추가 요청에 따라 `outputs/CONTRACT-AUDIT-01-probes.py`를 저장했다. 현 0.2 API의 함수별 expected rejection/value와 영역 표시를 포함하며 실제 실행 결과는 **18 FAIL / 1 BLOCKED / 0 PASS**였다. 모두 부정 경계를 겨냥한 감사 probe이므로 전체 테스트 suite 결과나 18개의 독립 P1을 의미하지 않는다. BLOCKED는 알려진 manager import다. 코드가 아니라 입력 payload를 구성하는 probe이며 런타임 monkeypatch/소스 수정을 하지 않는다(DB/network 호출 차단만 적용).

작성물은 현재 projectless outputs의 본 보고서·인계·허용된 probe 파일 세 개다. 검토 저장소 시작/종료 status는 깨끗했고 HEAD는 고정 SHA였다. 런타임·테스트·설정 파일 수정, commit/push, 개인 DB/네트워크 접근은 하지 않았다. 실제 DB 검증, 최신 수정본, 전체 테스트, 통합 코드검토·최종 검증은 미검증으로 남긴다.
