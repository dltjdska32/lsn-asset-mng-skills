# CONTRACT-01 총괄 인수 검증 1차

2026-09-23. Gemini A 첫 결과, parent 68fab98. 신규 32개 test_contract 테스트는 동일 Python3.14 venv/PYTHONPATH gemini-a/runtime에서 0.384초 OK. 이것은 공통 계약 release 승인 아님. 아래 반례 때문에 B/C 배포를 보류하고 A에 수정을 회송한다.

실제 메모리 반례(개인 DB·네트워크 없음):

1. `decode_envelope({'contract_version':'0.2','kind':'UNRECOGNIZED','payload':{}})`가 그대로 ACCEPTED. 닫힌 타입/필드/typed 왕복 요구 미충족.
2. USD MONEY·period_end 지정 SlotSpec의 `matches_candidate('USD', None, None)`가 `(True,None)`. UNKNOWN dimension/period가 wildcard처럼 통과.
3. `validate_metadata_update_preservation`에 기존 snapshot_hash는 유지하고 payload.value를 1→999로 바꾼 metadata를 넣으면 그대로 ACCEPTED. hash 문자열 비교만으로 내용 변조를 막지 못함.

추가 직접 소스 확인:

- contracts/adapters.py가 providers.models를 import하므로 contracts stdlib-only 경계 위반.
- persist_contract_snapshot은 snapshot.run_id/selection_version와 manager run/current revision, bound evidence 존재/동일 run, calculation snapshot/binding 일치를 검증하지 않음. 과거 history 전량을 일반 metadata update로 교체할 수 있음. project_compatible=False 경로도 무결성 검사 필요.
- PublicAvailability DATE_INTERVAL은 시작/검증된 시간대 없이 임의 upper만으로 생성 가능. EXACT source locator 부재와 invalid enum을 엄격히 구분할 계약 필요.
- CalculationRecord 결과 payload가 mutable dict이며 lineage hash가 result_payload/unit/currency를 포함하지 않는다. 숫자/통화/결과 변경 탐지 누락. UNAVAILABLE/FAILED에서도 numeric output 허용 가능.
- 공통 DTO의 decode는 snapshot/calculation 일부만 수동 지원하고 financial/bar/13F typed roundtrip과 unknown field 검증이 없다. bool('false') 같은 강제 변환 금지.

판정: CHANGES_REQUIRED. 실행 기록은 32 pass와 위 세 actual counterexample, 나머지는 static finding으로 구분. 후속 1차 수정이 이 반례와 독립 리뷰 F01–F07을 충족해야 계약 baseline을 공유한다.

## 후속 직접 실행

- 최초 구현 commit f1b9caa. 1차 수정73d376e: 37개 contract 테스트, failures2/errors10. import와 중첩 wire/호출 API 불일치. 새 독립 CONTRACT-AUDIT-01에 이 고정 SHA를 전달했다.
- 2차 수정1462fb6: contract55개, errors2(bound_value 필드 오타·cross-run fixture의 FK 위반). independent memory probes를 같은 수정본에 실행:17FAIL/2PASS. nested kind와 manager import는 해결됐으며 남은 불변식은 CONTRACT-FIX-03으로 회송.
- 1462fb6의 별도 고정 폴더 contract-test-1462에서 전체 unittest discover 실행:342개,47.748초,errors2. 두 오류는 위 계약 테스트와 동일했고 기존287개 회귀에서 추가 실패는 없었다. Python3.14.6 저장소 venv, PYTHONPATH는 해당 고정 worktree/runtime로 확인했다. 수정 중인 gemini-a 파일은 이 전체 검증에 사용하지 않았다.
- 각 실행 raw log/receipt는 해당 worktree의 ignored workspace/runs에 보존. 실제 개인DB·자동주문·원격배포 수행 없음. full pass 또는 공통계약 인수로 간주하지 않는다.
