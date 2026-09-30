# GEMINI31-A-SEC-03 — SEC-02 검증 오류와 차원 허용목록

Gemini 3.1 Pro High A, 같은 격리 worktree, HEAD `65388c1` + SEC-01/02 WIP. 소유는 `providers/adapters.py`, `tests/unit/test_r04_sec_companyfacts.py`, 새 `handoffs/GEMINI31-A-SEC-03.md`만. 파일 읽기/쓰기만; RunCommand/shell/git/tests/pip/web 금지. R02–04, DESIGN-v0.1.

총괄 직접 SEC-02 신규 테스트 5개 실행: **1 ERROR**, `test_missing_required_fields_marks_partial`에서 observations.sort의 metadata `start`/`period_end`/`accn` 중 None과 str 비교 TypeError. 모든 정렬키를 타입 안정적으로 만들고 `float(o.value)`로 Decimal 정밀도를 잃지 말라. 순열 불변성을 tests에서 사실상 검증하라. `_SEC_SUPPORTED_TAGS` unit kind 검증은 현재 money에 임의 문자열 `garbage`/`foo`, per-share에 `foo/shares`를 허용하므로 명시 지원 통화·단위만 인수하게 좁혀라(최소 USD, USD/shares, shares; 지원 범위 제한은 handoff에 표시). 잘못된 form을 승인하지 말고 SEC 10-K/10-Q 및 각각 `/A`의 명시 허용목록(필요 시 공식 근거 없으면 더 좁게)을 적용하라. duration fact의 period start/end와 공개일을 metadata에 둘 뿐 실제 FinancialSet 비교는 후속이라고 정확히 기록하라. 기존 빈 Revenue AVAILABLE test는 총괄이 R04와 맞게 갱신한다. 수정 뒤에는 스스로 테스트 통과 주장 금지, 총괄에게 재실행 요청.
