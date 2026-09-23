# CONTRACT-AUDIT-04 인계

고정 대상 `gemini-a`의 `49837ea3072914a00a7c65eff484789ea94d050a`. runtime tracked diff 없음. 시작부터 untracked 문서 두 항목이 있어 전체 clean 주장은 하지 않음.

**메모리 typed gate 검사 12개: 10 PASS / 2 FAIL / 0 BLOCKED.** 기존 audit-02 gate_calculation_link BLOCKED를 새 gate_refs + validate_calculation_for_use의 실제 호출로 보완했다. 원 probe는 수정하지 않았다.

통과: disabled gate 거부(왕복 후 포함), 검증 gate 정상 출력, 미승인/미검증13F 및 미등록gate 차단, 알려진13F formula의 requirement 완화 거부, 일반 산술/명시적 CONDITIONAL scenario 유지, unavailable 소비 불가.

필수 P1 두 가지:

1. `calculation.py:581` 이후 record와 gate purpose를 비교하지 않아 UNRELATED_DIAGNOSTIC gate로 13F_WEIGHT 출력을 소비할 수 있다. 요구 용도와 적용 policy identity를 연결해 대조해야 한다.
2. `calculation.py:543` formula 이름 패턴 외에는 explicit requirement를 허용한다. 동일13F_WEIGHT·WEIGHT출력·DISABLED gate를 유지하고 formula=`portfolio_weight_v2`, requirement=`ARITHMETIC`으로 지정하면 is_consumable=True다. 신뢰된 formula_id/version requirement 등록과 purpose/output 일관성이 필요하다.

실제 DB 저장은 금지 범위라 실행하지 않았다. encode/decode는 저장 형식 검사일 뿐 저장 승인 검사로 계산하지 않는다. runtime 정적 검색상 validator는 정의/export만 있고 저장·compiler caller는 발견되지 않았다. 전체 소비 강제는 후속 통합 확인 사항이다. 합성 approval/validation 참조의 실존·진위도 검사하지 않았다.

산출물: CONTRACT-AUDIT-04.md, CONTRACT-AUDIT-04-probes.py, CONTRACT-AUDIT-04-handoff.md.

```powershell
& 'C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 -B outputs/CONTRACT-AUDIT-04-probes.py --repo C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a
```

네트워크·모든 DB 접근은 스크립트에서 차단. source 수정·설치·git commit 없음. 기존 storage blocker, 전체 코드 REVIEW/최종 VERIFY는 별도 후속 범위로 유지한다.
