# CONTRACT-AUDIT-02 인계

- 고정 대상: `C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit`, `fdd64f05e3c8eb717a6ed2444cc5fb4b9727559e`.
- 메모리 전용 새 probes 28개: **9 PASS / 19 FAIL / 0 BLOCKED**. 기존 audit-01 probe는 수정하지 않았다.
- 대상 코드 수정·설치·네트워크·개인 DB 접근 없음. CA01/02/06과 진행 중인 CONTRACT-FIX-04 storage 변경은 제외했다.

필수 계약 수정 네 묶음:

1. **CA03 strict decode:** duplicate JSON 키, raw NaN token, unknown provider field를 거부한다. bool→source_tier 1, `"false"`→True 변환을 없애고 모든 public decoder를 같은 strict 경계에 연결한다.
2. **CA04 gate:** purpose 공백에 따른 우회와 policy_id의 `unapproved` 부분 문자열 오탐을 없앤다. 13F의 승인·검증 조건을 명시하고 정책 필요 계산과 gate를 typed 계약으로 연결한다. 단순 필드 추가만으로 validator 완료를 판정하지 않는다.
3. **CA04 output:** unavailable payload의 nested/한국어 숫자 우회와 정상 price_error 진단 오탐을 typed output/diagnostic 분리로 해결한다. 임의 key 이름이나 모든 metadata 숫자 금지로 대체하지 않는다.
4. **CA07 adapter:** 두 ProviderObservation decoder의 의미를 일치시키고 confirmation/cluster/relevance를 보존한다. normalized SHARES/EPS에 canonical unit을 쓴다. quote projection은 provenance를 보존하거나 표시 전용·계산 승격 불가 경계를 명시한다.

별도 P2: payload 직접 변경이 가능하나 verify_lineage=False로 탐지된다. immutable 보장 또는 소비 시 검증이 필요하며, 이번 결과를 저장소의 무탐지 변조라고 해석하지 않는다.

유지할 정상 동작: 일반 산술은 승인 없이 CALCULATED, 명시적 미승인 analyst scenario는 CONDITIONAL. nested kind/unknown field 거부, numeric NaN 거부, quote/13F PRN·voting 왕복, MONEY canonical unit, 원본 dict 변경 격리도 통과했다.

계약 확정 전 수정과 후속 통합을 분리한다. typed gate/output 및 lossless DTO 경계는 B/C 공용 인터페이스 확정 전에 필요하다. 실제 참조 해석, renderer 소비 차단, storage와의 결합은 후속 통합에서 확인하며 모든 분석 알고리즘 완료를 기다릴 필요는 없다.

**D18 반영:** common acceptance 미완료 상태에서 A storage 수정과 B/C의 단독 소유 parser·수학식·13F 비교 구현을 병행한다. B/C는 fdd64f0을 명시적 미인수 초안으로 사용하고 공통 파일 수정·validator 우회 없이 작업한다. 최종 contract sync·retest 후에만 통합하며 전체 REVIEW/VERIFY는 후속 새 세션으로 유지한다.

**A에 전달할 최소 API:** formula_id/version별 신뢰된 requirement와 닫힌 purpose, lineage에 포함되는 typed gate_refs, 공용 `validate_calculation_for_use(record, context)` 경계, compiler가 소비하는 검증 결과 wrapper, typed outputs와 diagnostics 분리. 공용 validator가 gate의 용도·정책 identity·state·승인/검증 요구를 확인하고 compiler는 그 결과만 소비한다. 일반 산술/명시적 scenario 대조군을 유지한다. 상세 보고서 마지막 절에 구체적 책임 및 최소 fixture를 적었다. API 명칭은 제안이며 새 서명 체계나 대규모 정책 프레임워크 요구가 아니다.

재현:

```powershell
& 'C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 -B outputs/CONTRACT-AUDIT-02-probes.py --repo C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit
```

FAIL과 BLOCKED를 구분하며 올바른 거부로 인정하는 예외는 ContractValidationError 계열뿐이다. 새 gate API가 생기면 gate_calculation_link는 BLOCKED로 전환되므로 실제 binding 검사를 보강해야 한다. 전체 상세 근거와 probe별 결과는 `CONTRACT-AUDIT-02.md`, 재현 코드는 `CONTRACT-AUDIT-02-probes.py`에 있다.
