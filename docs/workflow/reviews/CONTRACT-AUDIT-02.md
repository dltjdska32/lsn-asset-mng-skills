# CONTRACT-AUDIT-02 — CA03/04/07 잔여 계약 감사

검사 대상: `C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit`  
고정 커밋: `fdd64f05e3c8eb717a6ed2444cc5fb4b9727559e`  
실행 환경: Python 3.14.6, contract version `0.2`  
결과: **28개 중 9 PASS / 19 FAIL / 0 BLOCKED**

**판정: CA03/04/07을 모두 닫거나 공용 계약을 확정하기에는 아래 P1 네 묶음이 남아 있다.** 19개 실패는 독립적인 P1 19개를 뜻하지 않는다. API 수준 의미 불일치와 계약 연결 부재를 재현했으며, 실제 주문·보고서 생성이나 DB 저장 우회가 발생했다고 판정한 것은 아니다.

## 범위와 재현

메모리에서 만든 합성 DTO만 사용했다. 대상 코드 수정, 설치, 네트워크, 개인 데이터 및 DB 접근은 하지 않았다. probe는 Python socket 연결과 sqlite3 연결을 명시적으로 차단한다. CA01/02/06 및 진행 중인 CONTRACT-FIX-04의 canonical evidence/value binding, full-scope snapshot, storage read/reopen 검증은 이번 범위에서 제외했다.

```powershell
& 'C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 -B outputs/CONTRACT-AUDIT-02-probes.py --repo C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit
```

`FAIL`은 기대한 계약 의미와 관찰 결과의 불일치다. 잘못된 입력의 거부는 `ContractValidationError` 계열만 PASS로 인정한다. 예상 밖 API/환경 예외는 BLOCKED이며, 정상 입력이 validation 오류로 거부되면 FAIL이다. 실패가 있으므로 종료 코드는 1이다. 원래 `CONTRACT-AUDIT-01-probes.py`는 수정하지 않았다. 기존 19 probes 및 전체 contract suite의 이번 재실행 결과는 이 보고서에 포함하지 않는다.

## P1-01 — strict decode가 JSON 및 일부 DTO 경계에서 풀린다 (CA03)

근거: `runtime/investment_stack/contracts/codec.py:329`, `contracts/market.py:251`, `contracts/institutional.py:293`, `providers/contract_adapters.py:187`, `providers/models.py:72`.

| 입력 / probe | 관찰 결과 |
|---|---|
| `duplicate_json_approval`: 동일 객체에 `is_approved:false,is_approved:true` | 마지막 값 True로 승인 의미가 결정됨 |
| `nonfinite_json_assumption`: JSON의 raw `NaN` token | assumption.value가 문자열 `nan`으로 변환되어 수용됨 |
| `unknown_provider_field` | 알 수 없는 필드가 조용히 폐기됨 |
| `bool_source_tier` | True가 정수 1로 변환됨 |
| `string_false_quote` | `is_trade:"false"`가 True가 됨 |
| `string_false_holding_set` | `is_amended:"false"`가 True가 됨 |

승인, 거래 여부, 정정 여부, 출처 등급이 decode 과정에서 달라진다. JSON 경계에서 중복 키와 비표준 비유한 token을 거부하고, 모든 public decoder가 같은 허용 필드 및 strict scalar 검증을 사용해야 한다. 문자열 필드는 임의 객체를 `str()`로 세탁하지 않아야 한다. 숫자 필드의 유한성 검증만 강화해서는 raw NaN의 문자열 변환을 막지 못한다.

이미 고쳐진 부분도 확인했다. 잘못된 nested kind, nested PublicAvailability의 unknown field, quote price의 문자열 `NaN`은 거부된다. 정상 quote의 False boolean은 정확히 왕복한다.

## P1-02 — gate 판정이 문자열에 의존하고 계산에 연결되지 않는다 (CA04)

근거: `contracts/calculation.py:71`, `:103`, `:131`.

- `purpose_spelling_bypass`: 승인 없는 `TRADING`/CONDITIONAL은 DISABLED가 되지만 `TRADING `은 CONDITIONAL로 남는다.
- `unvalidated_13f_enabled`: 13F_AGGREGATE에서 approval_ref만 있고 validation_ref가 없어도 ENABLED가 된다.
- `policy_id_word_false_positive`: 승인·검증 참조가 있는 합성 정상 fixture도 policy_id에 `unapproved`라는 부분 문자열이 들어가면 DISABLED가 된다. ID는 승인 상태의 근거가 아니다.
- `gate_calculation_link`: DISABLED인 13F gate와 CALCULATED/5인 CalculationRecord를 함께 만들 수 있다. record에는 typed gate 연결이 없고, 자유 payload의 `gate_ref`와 `score_status:"UNVALIDATED"`는 검증되지 않는다.

마지막 검사는 **계약 API의 연결 부재**를 재현한다. 자유 payload의 문자열만으로 실제 계산이 그 gate에 속한다는 점이나 운영 소비자가 결과를 사용했다는 점까지 증명하지는 않는다. 바로 그 연관성을 명시할 typed 계약과 공용 검증 경계가 필요하다. 향후 gate 필드만 추가되면 이 probe는 BLOCKED를 반환하도록 작성했다. 새 API에 실제 disabled gate를 바인딩해 거부되는지 검사하도록 갱신해야 한다.

필수 계약은 닫힌 용도 분류 또는 신뢰된 formula requirement 정의, 정책 식별자와 상태의 분리, 13F 승인·검증 조건, 계산/출력과 gate의 typed 참조 및 공용 검증이다. 용도·정책 이름·source의 임의 키워드로 제한을 결정하지 않는다. 승인/검증 참조가 실제 대상에 대응하는지 확인하는 통합 구현은 별도이며, 이번 합성 참조가 실제 승인을 증명한다는 뜻은 아니다.

정상 대조군인 일반 산술 `2+3=5`는 승인 없이 CALCULATED로 통과했다. 명시적 ANALYST_SCENARIO 가정이 미승인인 경우 CONDITIONAL/101도 통과했다. 수정 후에도 이 구분을 유지해야 한다. 모든 산술에 투자 정책 승인을 요구하거나 설명용 시나리오를 일괄 금지할 필요는 없다.

## P1-03 — unavailable 출력 제약이 key 이름에 의존한다 (CA04)

근거: `contracts/calculation.py:169`.

`nested_unavailable_numeric`는 UNAVAILABLE에 `{"details":{"entry":Decimal("100")}}`을, `localized_unavailable_numeric`는 `{"진입가":"100"}`을 넣어도 수용한다. 둘 다 lineage 검증은 통과한다. 반대로 정상 진단문 `{"price_error":"source unavailable"}`은 키에 price가 있다는 이유로 거부된다 (`unavailable_text_diagnostic`).

자유 payload만으로 숫자가 투자 출력인지, 진단용 표본 수인지 신뢰성 있게 구별할 수 없다. 소비 가능한 수치·행동 출력을 typed 필드로 정의하고, 진단 metadata를 별도로 다뤄야 한다. UNAVAILABLE/FAILED의 소비 가능한 출력은 null/없음이어야 하며 렌더러는 그 검증된 필드만 사용해야 한다. 단순 재귀 숫자 금지나 키워드 목록 확장은 정상 진단 수치까지 차단할 수 있다.

필수 P1은 이 출력 경계의 계약 정의와 검증이다. 특정 보고서가 위 payload를 진입가로 표시하는지는 이번에 실행하지 않았으며 소비 경로 통합 검사로 남긴다.

## P1-04 — provider 공용 계약에서 의미와 단위가 손실된다 (CA07)

근거: `providers/contract_adapters.py:27`, `:68`, `:187`, `providers/models.py:63`.

| probe | 관찰 결과 / 영향 |
|---|---|
| `provider_semantic_roundtrip` | 등록 decoder가 official_confirmation_status, event_cluster_id, relevance_reason을 모두 None으로 만듦 |
| `provider_decoders_agree` | 동일 envelope의 classmethod decode와 등록 decode 결과가 다름 |
| `normalized_shares_unit` | normalized 2000에 raw unit `thousand shares`가 붙음 |
| `normalized_eps_unit` | normalized 2000에 raw unit `USD thousand/share`가 붙음 |
| `quote_provenance_projection` | quote projection에서 evidence_id와 PublicAvailability locator를 찾을 수 없음; source_url도 None |

첫 네 항목은 decode 경로 및 계산 입력의 의미가 달라지는 계약 결함이다. 공용 decoder 하나를 사용하고 모든 선언된 의미 필드를 보존해야 한다. normalized value에는 차원별 canonical unit을 붙이고 raw unit/scale은 별도 보존한다. 이미 MONEY는 `2000 USD`로 정상 투영되는 것을 확인했다.

quote provenance 손실은 projection의 용도에 따라 종료 조건이 달라진다. 계산 경계로 사용할 계약이면 원본 typed envelope 또는 해석 가능한 evidence/availability 참조를 보존해야 한다. 표시 전용이면 그 제한을 선언하고, eligibility·calculation 입력으로 승격할 수 없도록 소비 경계를 정의해야 한다. 모든 표시 projection이 무조건 원본으로 역변환 가능해야 한다는 요구는 아니다. 참조 실존성과 storage binding 검증은 FIX-04와의 후속 통합 대상으로 남긴다.

## P2-01 — payload는 복사되지만 immutable하지 않다

근거: `contracts/calculation.py:186`.

`copied_input_control`은 통과한다. 호출자가 전달했던 원래 dict를 바꿔도 record는 변하지 않는다. 하지만 `direct_payload_mutation`에서 `record.result_payload["details"]["value"] = "999"`가 성공한다. frozen dataclass는 내부 dict까지 동결하지 않는다.

변경 후 `verify_lineage()`는 False이므로 탐지 기능은 작동한다. 따라서 이를 저장소의 무탐지 변조 또는 독립 P1로 확대하지 않는다. immutable typed payload/재귀 동결을 적용하거나, 소비 경계가 검증 실패 객체를 거부하도록 보장하고 immutable이라는 API 설명을 실제 보장에 맞춰야 한다. 소비 경계의 검증 여부는 후속 통합 확인 사항이다.

## 전체 probe 결과

| 결과 | probe |
|---|---|
| PASS | wrong_nested_kind |
| PASS | unknown_nested_field |
| FAIL | duplicate_json_approval |
| FAIL | nonfinite_json_assumption |
| PASS | nonfinite_price |
| FAIL | unknown_provider_field |
| FAIL | bool_source_tier |
| FAIL | string_false_quote |
| FAIL | string_false_holding_set |
| PASS | quote_roundtrip |
| FAIL | purpose_spelling_bypass |
| FAIL | unvalidated_13f_enabled |
| FAIL | policy_id_word_false_positive |
| FAIL | gate_calculation_link |
| PASS | ordinary_arithmetic |
| PASS | explicit_scenario |
| FAIL | nested_unavailable_numeric |
| FAIL | localized_unavailable_numeric |
| FAIL | unavailable_text_diagnostic |
| PASS | copied_input_control |
| FAIL | direct_payload_mutation |
| FAIL | provider_semantic_roundtrip |
| FAIL | provider_decoders_agree |
| PASS | money_unit_control |
| FAIL | normalized_shares_unit |
| FAIL | normalized_eps_unit |
| FAIL | quote_provenance_projection |
| PASS | holding_roundtrip_control |

## B/C 계약 확정 및 후속 작업 기준

공용 DTO 확정 전에는 P1-01의 strict decode, P1-02의 gate binding/용도 계약, P1-03의 typed output/diagnostic 구분, P1-04의 lossless decode와 normalized 단위 계약을 정리해야 한다. quote projection의 계산 사용 가능 여부도 명시해야 한다.

D18 일정 결정에 따라 common acceptance는 미완료로 유지하되, A storage 수정과 동시에 B/C는 fdd64f0의 명시적 미인수 초안에서 source parser·수학식·13F 비교 등 단독 소유 파일 작업을 병행한다. 공통 파일 수정 및 validator 우회 없이 진행하고 최종 contract sync·retest 이후에만 통합한다. 이는 현재 공통 계약이 통과했다는 판정이 아니다. 별도 전체 REVIEW/VERIFY는 후속 새 세션 범위다.

후속 통합에서는 실제 gate 참조 해석, disabled·unvalidated 정책의 소비 차단, unavailable 출력 렌더링 제한, provenance 참조 해석, 변조 lineage 거부를 확인한다. 모든 평가 알고리즘의 완성을 B/C 시작 조건으로 삼을 필요는 없다. 이번 결과는 제외된 CA01/02/06의 완료 여부를 판정하지 않는다.

## A의 다음 보완을 위한 최소 API 제안

아래는 제안이며 현재 구현되었거나 인수되었다는 뜻은 아니다. 별도 서명 인프라나 대규모 정책 프레임워크는 필요하지 않다.

1. **용도와 요구 조건:** 닫힌 `CalculationPurpose` 및 공용 `FormulaRequirement` 정의를 둔다. requirement는 formula_id/version에 연결하고 `requires_approval`, `requires_validation`, 허용 output 종류를 명시한다. 호출자가 임의 문자열이나 임의 boolean으로 정책 필요 여부를 해제할 수 없어야 한다. 일반 산술은 gate 불필요로, 설명용 scenario와 정책 민감 계산은 별도 용도로 구분한다.
2. **gate binding:** CalculationRecord에 typed `gate_refs`를 추가하고 계산의 purpose/requirement 식별자와 함께 lineage에 포함한다. 공용 facade가 같은 run의 gate를 해석하여 policy_id/version/hash와 용도가 일치하는지, 필요한 승인·검증 및 state 조건이 충족되는지 확인한다. DISABLED 또는 검증되지 않은 13F 정책으로 소비 가능한 점수·비중을 만들 수 없어야 한다. 참조 문자열의 존재만으로 통과하지 않는다.
3. **계산과 compiler 사이의 단일 경계:** 예를 들어 `validate_calculation_for_use(record, context)`가 검증된 결과 wrapper를 반환하고 compiler는 이를 입력으로 받는다. context의 snapshot/evidence/storage 해석은 FIX-04 facade에 연결한다. compiler가 별도의 keyword 검사나 별도 승인 판단을 구현하지 않도록 한다. API 이름보다 이 단일 검증 책임과 소비 경계가 핵심이다.
4. **출력 DTO:** `outputs`는 종류·값·단위·통화가 선언된 typed tuple로, `diagnostics`는 별도 구조로 둔다. UNAVAILABLE/FAILED이면 소비 가능한 outputs는 비어 있어야 한다. CONDITIONAL의 설명용 수치는 조건과 함께 표현하되, disabled 정책의 투자 행동·13F score/weight로 승격하지 않는다. compiler는 자유 metadata에서 숫자·행동을 추출하지 않는다.

최소 인수 fixture는 disabled gate 거부, approval만 있는 unvalidated 13F 거부, 정상 검증 gate 수용, 다른 용도/정책 gate 연결 거부, unavailable output 차단, 정상 텍스트 진단 허용, 일반 산술 및 명시적 scenario 유지다. gate API 도입 후 기존 구조 검사 probe를 이 facade의 실제 binding 검사로 교체하고, storage·compiler 통합 검증은 후속 세션에서 수행한다.
