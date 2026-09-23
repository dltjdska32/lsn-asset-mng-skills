# CONTRACT-AUDIT-03 — bounded storage acceptance

대상: `C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit`  
고정 SHA: `84633e567c304735442749c24925a910b1694586`  
범위: CA01 / CA02 / CA06, CONTRACT-FIX-04의 금융입력 binding·snapshot·scope·storage read/reopen  
최종 실행: **29 probes = 7 PASS / 6 FAIL / 16 BLOCKED**, 종료 코드 1  
판정: **storage acceptance 미완료. 유효 금융입력의 정상 등록→snapshot→계산 저장→reopen 재현 경로는 통과를 입증하지 못했다.**

## 검사 방법과 결과의 한계

Python 3.14.6에서 실제 `PublicAvailability.exact(..., locator=...)`, 필수 metric이 있는 `SlotSpec`, 유효 `MarketQuote` 및 `Holding13F`를 사용했다. quote 자체의 typed encode/decode 왕복은 통과한 뒤 등록 함수에서 중단됐다. 기존 테스트의 `instant()`나 metric 누락을 그대로 복제하지 않았다.

대상 파일 수정·monkeypatch·설치·네트워크·개인 DB 접근·commit은 하지 않았다. 새 스크립트는 `work/` 아래 TemporaryDirectory에서 만든 합성 run.db와 SQLite 메모리 DB만 허용하며 종료 시 임시 DB를 정리한다. 실제 금융자료는 없다. 기존 19/28/5 probe는 수정하지 않았으며 이번에 재실행하지 않았다. 전체 84 tests도 재실행하지 않았다. FIX-05의 fixture·CA03/04/07 gate/codec 및 별도 최종 code REVIEW/VERIFY는 제외했다.

BLOCKED는 올바른 validation 거부가 아니다. 실제 API 실행 오류와 그 의존 검사들을 별도 집계했다. 이번 16 BLOCKED의 근본 원인은 아래 세 runtime 결함이다. FAIL 6개도 서로 독립적인 P1 6개로 세지 않는다.

정상 쓰기 경로가 막힌 상태에서 나머지 범위를 분리하기 위해 두 가지 제한된 보조 fixture를 사용했다.

- **빈 snapshot:** 실제 public API로 저장한다. scope·history 동작만 검증하며 금융입력 승인이나 계산 재현의 정상 대조군으로 간주하지 않는다.
- **SQL-seeded read fixture:** 실제 API로 등록된 Holding13F와 실제 DTO/hash/envelope로 일관된 snapshot ledger를 합성 임시 DB에 직접 넣는다. 먼저 정상 읽기를 확인하고 손상 또는 모순을 주입한다. 이 경로는 read validator 및 calculation input 비교를 분리 검사하기 위한 것으로, snapshot 쓰기 API 통과를 뜻하지 않는다. 대상 코드나 검증 함수는 변경하지 않는다.

## P1-01 — 정상 금융입력/계산 저장이 세 runtime 오류로 중단됨

| 실행한 정상 경로 | 실제 중단 위치와 오류 | 최소 수정 |
|---|---|---|
| 유효 exact MarketQuote → `add_contract_evidence` | `contracts/storage.py:57`, `PublicAvailability.available_at` AttributeError | 실제 DTO의 `public_available_at` 사용. DATE_INTERVAL/UNKNOWN도 명시적으로 처리하고 검증된 availability 의미를 보존 |
| 실제 typed Holding13F 등록 → 금액 20 snapshot 저장 | `evidence/manager.py:963`, `Decimal` NameError | 사용하는 Decimal을 import하고 동일 정상 경로 재실행 |
| SQL-seeded 정상 snapshot → 독립 계산 저장 | `evidence/manager.py:1341`, `CalculationRecord.preceding_calculation_ids` AttributeError | 실제 DTO와 저장 코드의 선행 계산 참조 계약을 일치시킴 |
| 빈 snapshot + 정상 상수 계산의 atomic 저장 | `evidence/manager.py:1047`, 동일 AttributeError | atomic/독립 두 경로 함께 수정·재검증 |

첫 문제는 FinancialFact/Bar projection에도 동일 속성 접근이 있다(`storage.py:71`, `:85`). 이 두 DTO 경로까지 실행한 것은 아니며 정적 확인이다. 선행 계산 ID 문제도 단순 fixture 오류가 아니라 실제 record API에 없는 필드를 저장 함수가 요구하는 문제다. 새로운 기능을 억지로 추가할 필요 없이 기존 BoundSlotInput의 calculation_id 등 의도된 참조 모델과 일관되게 정리하면 된다.

이 상태에서는 canonical value/currency 거부 검사가 NameError로 끝나도 보안·무결성 PASS로 계산할 수 없다. immutable S1/S2의 **금융 값** 보존 및 계산 결과 재현도 아직 미확인이다.

## P1-02 — 값 없는 임의 projection이 임의 금액의 snapshot을 승인함 (CA01)

실행 재현 `incomplete_projection_cannot_authorize_value`:

1. public `add_evidence`로 raw evidence를 등록한다.
2. metadata는 `{"canonical_payload":{"contract_kind":"MarketQuote"}}`만 넣는다. typed envelope, 값, 단위, 통화는 없다.
3. 이 evidence_id를 참조하는 금액 999 / CURRENCY / USD의 BoundSlotInput을 snapshot에 넣는다.
4. `persist_contract_snapshot`이 성공한다.

근거: `evidence/manager.py:955`는 nonempty dict 여부만 확인하고 `:962`는 canonical_value가 **있을 때만** 비교한다. 값이 없으면 Decimal NameError마저 건너뛰면서 성공한다. 따라서 등록된 evidence 행 또는 canonical_payload라는 metadata 이름 자체가 typed 검증을 대신하고 있다.

최소 수정은 snapshot binding 시 원래 typed envelope를 decode하고 허용된 종류의 완전한 canonical projection을 재도출하는 것이다. 원본과 projection의 ID/값/단위/통화/availability 의미를 검증해야 한다. 일반 `add_evidence`의 임의 metadata는 계산 입력을 승인할 수 없어야 한다. projection을 캐시로 유지한다면 재도출한 값과 일치하는지도 확인한다. 새 서명 체계는 필요 없다.

### 바인딩 필드별 확인 수준

| 경계 / 필드 | 이번 실행 결과 | 정적으로 확인한 제한 |
|---|---|---|
| evidence → snapshot 값 | 정상 값 포함 경로 및 값 불일치 모두 BLOCKED | 값 누락 시 비교 생략은 위 FAIL로 실행 확인 |
| currency / instrument | 불일치 검사 BLOCKED | currency는 양쪽이 non-null일 때만 비교; instrument도 snapshot 값 존재 시 비교 |
| canonical_unit | BLOCKED | snapshot 저장 루프에 canonical unit 비교 없음 |
| public_available_at | quote 등록부터 BLOCKED; holding의 임의 시각 검사도 Decimal에서 BLOCKED | 저장 루프에 availability 비교나 cutoff 검증 없음 |
| evidence provenance / fingerprint | quote evidence_id 불일치 및 holding fingerprint 검사 BLOCKED | 등록 시 envelope evidence_id와 row ID 비교 없음; snapshot 저장 시 input_fingerprint 검증 없음 |
| eligibility_id | 존재하지 않는 ID 검사 BLOCKED | snapshot 저장 루프에서 EligibilityDecision을 해석·검증하는 연결 없음 |
| calculation → 이미 저장된 snapshot | **PASS**: value/unit/currency/evidence/observation/calculation/eligibility/public/fingerprint의 9개 필드 변경 모두 InputIntegrityError | 공용 `_validate_bound_slot_match`의 전체 canonical 비교가 작동. 최초 snapshot 내용이 실제 evidence에 검증됐다는 뜻은 아님 |

unit/public/eligibility/fingerprint의 부재는 **정적 결함 후보 및 후속 필수 인수 항목**이다. 이번 runtime에서 그 공격 입력이 저장에 성공했다고 확대하지 않는다. eligibility가 별도 selector에서 결정된다면 저장 경계가 검증된 결정의 참조·용도·입력 fingerprint를 확인할 수 있어야 한다. 전체 정책 evaluator 구현을 요구하는 것은 아니다.

## P1-03 — 읽기에서 객체 간 binding과 active scope를 재검증하지 않음 (CA02/06)

### 실제 public snapshot 저장으로 재현한 scope 오류

`same_instrument_two_request_scopes`는 정상 통과했다. 같은 종목/목적에서 as_of가 다른 두 SelectionRequest의 hash는 다르고, 각각의 active snapshot을 찾을 수 있다. request_hash를 생략하면 AmbiguousSnapshotError로 거부한다. 이 대조군은 빈 snapshot이다.

`read_rejects_wrong_scope_existing_pointer`는 FAIL이다. 두 scope의 빈 snapshot을 정상 API로 저장한 후, request A의 active pointer만 기존 request B snapshot hash로 바꿨다. reopen 후 A를 지정해 조회하면 B의 snapshot을 반환한다. hash 자체는 모두 유효하며 포인터 대상도 history에 존재한다.

근거: `contracts/storage.py:224`는 target hash의 존재만 검사한다. `evidence/manager.py:1177`의 fetch는 pointer key를 필터링한 뒤 대상 snapshot의 실제 purpose/instrument/request를 재확인하지 않는다.

**최소 수정:** active key와 대상 snapshot.active_key 및 조회 scope가 일치해야 한다. 구형 wildcard 지원이 필요하면 그 규칙을 명시하고 모호한 결과를 거부한다. 참조 대상이 존재한다는 사실만으로 scope를 인정하지 않는다.

### SQL-seeded fixture로 분리한 계산 read 오류

`calculation_full_slot_match`는 아홉 필드의 변경을 write API가 거부했다. `historical_snapshot_reference_not_current`도 PASS: S1=20, S2=30으로 합성한 이력에서 S1 hash를 참조하면서 S2의 bound inputs를 쓰면 InputIntegrityError다. 이 두 검사는 seeded snapshot에 대한 **실제 계산 저장 API의 거부**이며, 정상 계산 저장은 이후 별도 AttributeError로 막힌다.

반면 `read_rechecks_calculation_against_snapshot`는 FAIL이다. S1=20을 참조하면서 bound value=999인 계산을 만든다. 계산 자체의 lineage는 올바르다. 이 모순된 계산 envelope를 SQL로 ledger에 넣으면 reopen 및 `fetch_contract_calculations`가 허용한다. 쓰기 API가 거부할 객체 간 모순을 읽기는 허용하는 것이다. 저장 API로 이 모순이 삽입됐다는 주장은 아니다.

근거: `contracts/storage.py:234` 이하 ledger validator는 계산의 self-lineage와 referenced snapshot hash의 존재만 검사한다. 계산 bound inputs와 **그 hash의 실제 snapshot**을 대조하지 않는다.

**최소 수정:** write/read가 같은 full-bound comparison을 사용하도록 하고, read 시에도 snapshot을 hash로 해석해 각 bound input을 비교한다. 사용한 입력 subset은 허용할 수 있지만 snapshot에 없는 입력·중복·값/출처 불일치는 거부해야 한다. 전체 snapshot과 계산 입력 수를 무조건 같게 만들 필요는 없다.

### evidence 저장본과 캐시의 불일치

`read_rechecks_evidence_binding`는 FAIL이다. seeded snapshot=20과 원본 typed Holding13F=20은 유지하고 evidence의 canonical_payload 값만 999로 바꿨다. typed snapshot read는 이 저장소 내부 모순을 탐지하지 않는다. 이 결과는 **과거 snapshot 값이 변조됐다는 뜻이 아니다**. snapshot은 여전히 20이고 원래 envelope와도 일치한다. 문제는 이후 쓰기가 신뢰하는 projection 캐시의 불일치를 storage validation이 탐지하지 않는다는 것이다. 읽기 시 재도출한 typed 원본을 권위로 삼거나, 명시적 integrity 검사에서 캐시 모순을 거부하도록 P1-02와 함께 정리한다.

## request descriptor 연결 미완료 — scope key와 요청 충족을 구분해야 함 (CA02)

`request_hash_requires_resolvable_descriptor`는 FAIL이다. 어떤 SelectionRequest도 저장하지 않은 상태에서 request_hash=`unregistered-request`를 준 빈 snapshot을 저장할 수 있다. 실행 결과가 입증하는 것은 **request hash 문자열이 해석 가능한 descriptor에 바인딩되지 않는다는 사실**이다. 실제 값이 다른 metric/기간의 요구를 충족했다고 계산까지 승인된 것은 아니다.

정적으로 SelectionRequest는 hash 계산이 가능하지만(`contracts/slots.py:349`), `persist_contract_snapshot`에는 request descriptor 인자·registry lookup이 없고 저장 루프도 요청 슬롯 조건을 검사하지 않는다. 따라서 full scope 분리는 발전했지만 descriptor의 metric, 기간, quote kind, currency, as_of와 선택 입력 간 일치 검증까지 완료됐다고 볼 수 없다.

공통 계약 인수 전 최소 연결: snapshot 저장에 SelectionRequest 또는 해석 가능한 request ref를 전달하고 hash를 재계산한다. purpose/instrument 및 선택된 slot의 요구 조건을 검증한다. 불완전 coverage가 허용되는 요청은 missing을 명시적으로 보존하면 되며, 모든 snapshot에 무조건 모든 요청 슬롯을 요구할 필요는 없다. eligibility 평가 자체는 selector에 둘 수 있지만 그 결과와 요청·입력의 binding은 확인해야 한다.

## reopen와 typed read의 상태를 혼동하면 안 됨 (CA06)

`reopen_marks_corrupt_ledger_invalid`는 FAIL: latest_revision=999인 counter-tail corruption에도 `open().valid`는 True다. `_validate_run_connection`(`evidence/manager.py:111`)은 SQLite·schema·run identity를 확인하고 contract ledger를 검증하지 않는다.

다만 `read_rejects_counter_tail_corruption`은 **PASS**, stale snapshot hash도 `CorruptedStorageError`로 거부된다. 따라서 open.valid=True를 이유로 typed read까지 그 손상을 무시한다고 주장하지 않는다. open 단계에서 contract ledger 검증을 호출하거나, 적어도 structural-open 상태와 contract-validated 상태를 명확히 분리해야 한다. 단독 reopen 상태 문제의 우선순위는 P2이며, 앞 절의 실제 잘못된 scope/계산 반환은 P1이다.

## 최종 probe 결과

| 상태 | probe | 범위/fixture |
|---|---|---|
| BLOCKED | exact_quote_registration_and_snapshot | actual exact quote 정상 경로 |
| BLOCKED | typed_holding_snapshot_reopen_control | actual holding 정상 경로 |
| BLOCKED | raw_metadata_cannot_impersonate_typed_evidence | 값 포함 위조 projection |
| FAIL | incomplete_projection_cannot_authorize_value | 값 없는 raw projection; 실제 API 수용 |
| BLOCKED | registered_identity_must_match_envelope | actual quote evidence ID 불일치 |
| BLOCKED | canonical_value_mismatch | actual typed evidence |
| BLOCKED | canonical_currency_mismatch | actual typed evidence |
| BLOCKED | canonical_currency_omission | actual typed evidence |
| BLOCKED | canonical_unit_mismatch | actual typed evidence |
| BLOCKED | invented_public_time | actual typed holding |
| BLOCKED | unresolved_eligibility | actual typed evidence |
| BLOCKED | invented_fingerprint | actual typed evidence |
| BLOCKED | instrument_mismatch | actual typed evidence |
| BLOCKED | immutable_s1_s2_reopen | 실제 금융 값 S1/S2 쓰기 |
| BLOCKED | actual_calculation_persist_replay | seeded snapshot, actual calculation write |
| BLOCKED | atomic_snapshot_calculation_positive | empty snapshot + constant calculation |
| PASS | calculation_full_slot_match | seeded snapshot; 9개 필드 거부 |
| PASS | historical_snapshot_reference_not_current | seeded S1/S2; S1 참조에 S2 입력 거부 |
| BLOCKED | transaction_rolls_back_invalid_calculation | actual typed financial snapshot |
| PASS | same_instrument_two_request_scopes | empty snapshots; scope/ambiguity |
| FAIL | request_hash_requires_resolvable_descriptor | unresolved hash 수용 |
| PASS | read_rejects_stale_snapshot_hash | seeded read fixture |
| FAIL | reopen_marks_corrupt_ledger_invalid | actual empty snapshot의 counter 손상 |
| FAIL | read_rejects_wrong_scope_existing_pointer | actual empty scope snapshots |
| FAIL | read_rechecks_evidence_binding | seeded read fixture; projection 캐시 손상 |
| FAIL | read_rechecks_calculation_against_snapshot | seeded read fixture; 객체 간 모순 |
| PASS | seeded_read_control | 일관된 seeded ledger 정상 읽기 |
| PASS | empty_scope_history_reopen_control | empty S1/S2 보존만 확인 |
| PASS | read_rejects_counter_tail_corruption | actual empty snapshot; typed read 거부 |

## 인수 재개 순서

먼저 세 runtime 오류를 수정한 커밋에서 **동일 신규 probe**의 정상 금융 경로와 BLOCKED cases를 재실행한다. 이후 typed 원본 재도출/필수 projection, 요청 descriptor 연결, write/read 동일 binding, active pointer scope 검증을 완료한다. 통과 판정에는 정확한 금액·단위·통화·공개시각·출처·eligibility가 보존되는 valid MarketQuote → S1/S2 → 계산 → reopen/replay 정상 사례가 반드시 포함되어야 한다.

이번 결과는 A의 FIX-05 fixture·gate·codec을 중복 리뷰하지 않았으며, root의 기존 추가 storage 5 PASS나 전체 suite 결과를 대신하지 않는다. D18의 미인수 초안 기반 B/C 독립 파일 병행 방침은 변경하지 않는다. 최종 통합 code REVIEW/VERIFY는 후속 새 세션에서 수행한다.

재현 명령:

```powershell
& 'C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 -B outputs/CONTRACT-AUDIT-03-probes.py --repo C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit
```

검사 전후 SHA는 동일하며 대상 checkout은 clean이다.
