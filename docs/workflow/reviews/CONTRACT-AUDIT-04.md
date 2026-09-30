# CONTRACT-AUDIT-04 — 새 typed gate API 한정 검사

대상: `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a`
HEAD: `49837ea3072914a00a7c65eff484789ea94d050a`
결과: **12 probes = 10 PASS / 2 FAIL / 0 BLOCKED**
판정: 기존 audit-02의 gate API 부재 BLOCKED는 새 API로 실제 검사했다. disabled gate의 기본 소비 차단은 작동하지만 **두 의미적 우회가 남아 CA04 완료 판정은 불가**하다.

검사 전 runtime은 HEAD 대비 변경이 없었다. 다만 `docs/workflow/reviews/`, `docs/workflow/source-checks-2026-09-23.md`가 시작부터 untracked였으므로 전체 checkout clean이라고 주장하지 않는다. 이 문서들은 열거나 수정하지 않았다.

## 실제 검사한 경계

`CalculationRecord.create(..., gate_refs, purpose, requirement, typed_outputs)`와 공개 `validate_calculation_for_use(record, registered_gates=...)`를 직접 호출했다. disabled record를 encode/decode한 뒤에도 소비가 거부되는지 확인했다. 정상 gate의 approval_ref/validation_ref는 합성 참조이며 실제 승인 문서의 진위나 실존을 검증한 것이 아니다.

전부 메모리 검사다. DB·네트워크는 스크립트 audit hook으로 금지했다. quote 저장의 알려진 available_at 오류, 실제 calculation DB 저장 거부, compiler 전체 소비 흐름, 전체 storage 감사는 검사하지 않았다. serialization 가능 여부는 DB 저장 승인과 같지 않으며 disabled record를 보존하는 것 자체를 실패로 보지 않는다.

## P1-01 — 다른 용도의 gate로 13F 출력을 승인할 수 있음

`unrelated_gate_purpose_rejects`: 계산은 purpose=`13F_WEIGHT`, formula=`13f_weight`, requirement=`POLICY_VERIFICATION`, output=`WEIGHT 0.2`다. 연결한 gate는 purpose=`UNRELATED_DIAGNOSTIC`이며 ENABLED와 합성 approval/validation 참조를 갖는다. 함수는 **is_consumable=True**와 비중 출력을 반환한다.

근거: `runtime/investment_stack/contracts/calculation.py:581` 이후 gate ID·state·참조 유무만 확인하며 record purpose와 gate purpose를 대조하지 않는다. record에는 요구하는 policy_id/version/hash를 명시적으로 연결하는 필드도 없다(이 부분은 정적 확인).

최소 수정: 검증할 formula/purpose에 맞는 gate 용도를 대조한다. 적용 정책이 정해진 계산은 요구하는 policy identity/version/hash를 신뢰된 requirement 정의 또는 명시적 binding으로 확인한다. 다른 용도의 승인·검증 참조가 권한을 대신할 수 없어야 한다.

## P1-02 — formula 이름과 호출자 requirement로 disabled 13F gate를 우회

`renamed_formula_cannot_lower_13f_requirement`: purpose=`13F_WEIGHT`, typed output=`WEIGHT 0.2`, 동일 DISABLED gate_refs를 유지하고 formula_id만 `portfolio_weight_v2`, requirement만 `ARITHMETIC`으로 지정한다. 함수는 gate를 검사하지 않고 **is_consumable=True**를 반환한다.

근거: `calculation.py:543`의 get_formula_requirement는 formula 이름에 `13f`/`institutional`이 있으면 검증을 강제하지만, 해당 이름 패턴이 아니면 explicit requirement를 허용한다. `:570`에서 그 결과를 소비 판단에 사용한다. 정상 대조군으로 알려진 formula=`13f_weight`에서는 explicit ARITHMETIC을 지정해도 disabled gate를 거부했다.

최소 수정: formula_id/version의 요구 조건을 작은 신뢰된 등록표로 결정하고, 호출자가 이를 완화하지 못하게 한다. 미등록 정책 민감 formula는 거부하거나 보수적인 요구 조건을 적용한다. purpose/output 종류와 requirement의 일관성도 확인한다. 임의 이름 패턴을 늘리는 것으로 해결하지 않는다. 일반 산술과 명시적 CONDITIONAL analyst scenario는 유지한다.

## 결과 목록

| 결과 | probe / 확인 내용 |
|---|---|
| PASS | disabled_gate_consumer_rejects — 실제 gate binding 후 소비 거부 |
| PASS | disabled_gate_after_roundtrip_rejects — gate/record 왕복 후에도 거부 |
| PASS | validated_gate_consumable_control — 정상 합성 검증 gate의 출력 허용 |
| PASS | unapproved_13f_rejects — 승인 없는 13F 차단 |
| PASS | approved_but_unvalidated_13f_rejects — 승인만 있고 검증 없는 13F 차단 |
| PASS | unregistered_gate_rejects — 미등록 gate 참조 차단 |
| FAIL | unrelated_gate_purpose_rejects — 다른 용도 gate로 소비 허용 |
| FAIL | renamed_formula_cannot_lower_13f_requirement — 이름/requirement 변경으로 disabled gate 우회 |
| PASS | known_13f_formula_ignores_lower_requirement — 알려진 13F formula의 완화 시도 거부 |
| PASS | ordinary_arithmetic_control — 합성 산술 결과 5의 gate 없는 소비 허용 |
| PASS | explicit_scenario_control — 미승인 가정의 명시적 CONDITIONAL scenario 허용 |
| PASS | unavailable_not_consumable_control — UNAVAILABLE은 소비 불가·출력 없음 |

올바른 거부는 ContractValidationError 계열만 PASS다. 예상 밖 API 오류는 BLOCKED, 정상 입력의 예상 밖 validation 거부 또는 우회 허용은 FAIL이다.

## 통합 상태와 재현

정적 runtime 검색에서 validate_calculation_for_use는 정의와 export만 발견됐으며 저장/컴파일러 호출부는 발견되지 않았다. 따라서 **공개 소비 함수의 부분 검증 성공을 실제 DB 저장 또는 모든 소비 경로의 gate 강제로 확대할 수 없다**. 이 연결은 후속 통합 검증 대상이다.

```powershell
& 'C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 -B outputs/CONTRACT-AUDIT-04-probes.py --repo C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a
```

원본 `CONTRACT-AUDIT-02-probes.py`는 수정하지 않았다(SHA256 `A00EAC9807FEEACB7497FAD658310AF3B0B85EB9F5C12689CD686FCA7B8CF176`). target 편집·개인 DB·실제 자산·설치·commit은 없었다. 이번 검사는 전체 storage 감사/전체 코드 리뷰/최종 검증을 대체하지 않는다.
