# CONTRACT-AUDIT-03 인계

고정 SHA `84633e567c304735442749c24925a910b1694586`, 대상 `C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit`, 검사 전후 clean.

**29 probes: 7 PASS / 6 FAIL / 16 BLOCKED. Storage acceptance 미완료.** 실제 유효 금융입력의 등록→snapshot→계산→reopen 재현은 통과를 입증하지 못했다. BLOCKED를 validation PASS로 계산하지 않았다.

먼저 A가 수정할 실제 runtime 오류 세 가지:

1. `contracts/storage.py:57` 등: 유효 `PublicAvailability.exact()`에도 `.available_at`을 읽어 AttributeError. 실제 필드는 `.public_available_at`.
2. `evidence/manager.py:963`: canonical 값 비교에서 Decimal import 누락으로 NameError. genuine Holding13F 정상 등록 후 snapshot 저장에서 재현.
3. `evidence/manager.py:1047`, `:1341`: 실제 CalculationRecord에 없는 preceding_calculation_ids 접근. atomic/독립 저장 모두 실행 재현.

필수 잔여 계약 문제:

- **CA01 P1:** raw evidence의 `canonical_payload={"contract_kind":"MarketQuote"}`만으로 금액999 snapshot 저장 성공. typed envelope 재decode 및 필수 값/단위/통화/availability/provenance 재도출이 필요하다. 임의 metadata dict를 승인 근거로 삼을 수 없다.
- **CA02/06 P1:** 존재하는 다른 request scope의 snapshot으로 active pointer를 바꿔도 read가 허용한다. pointer key와 대상 snapshot scope를 대조해야 한다.
- **CA02/06 P1:** 계산 write는 snapshot과 9개 binding 필드 차이를 거부하지만, SQL로 넣은 self-lineage-valid 계산(value999)/snapshot(value20) 모순을 read는 허용한다. write/read가 같은 snapshot binding 검증을 써야 한다.
- **CA02 계약 연결:** request hash로 두 scope를 구분하고 모호한 조회를 거부하는 기능은 PASS. 그러나 미등록 문자열 hash도 수용하며 descriptor lookup/슬롯 요구 조건 검증 연결이 없다. SelectionRequest 또는 해석 가능한 ref를 저장 경계에 연결하는 최소 수정이 필요하다.
- evidence canonical projection 캐시를 바꿔도 read는 탐지하지 않는다. 과거 snapshot 자체가 변한 것은 아니다. typed 원본을 권위로 삼아 캐시 일관성을 확인하는 CA01 수정과 함께 처리한다.
- **P2:** counter 손상에도 open.valid=True. typed read는 해당 손상을 CorruptedStorageError로 거부한다. open의 schema 유효성과 contract 유효성을 구분하거나 open에서 ledger 검증을 호출한다.

실행/정적 구분:

- canonical unit/public/eligibility/fingerprint 최초 binding 검사 부재는 정적으로 확인했다. 실제 공격 성공 여부는 Decimal 오류에 막혀 BLOCKED다.
- 정상 quote DTO roundtrip은 실행됐지만 등록에서 중단됐다. 실제 financial S1/S2와 계산 재현은 미입증.
- read/full-match 격리를 위해 typed Holding13F 등록 + 실제 DTO/hash를 이용한 **SQL-seeded 합성 ledger**를 사용했다. 정상 write acceptance로 계산하지 않는다.
- 빈 snapshot의 S1/S2 및 두 request scope 저장·읽기는 PASS지만 금융 값 보존의 대조군은 아니다.

산출물: CONTRACT-AUDIT-03.md, CONTRACT-AUDIT-03-probes.py, CONTRACT-AUDIT-03-handoff.md.

```powershell
& 'C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 -B outputs/CONTRACT-AUDIT-03-probes.py --repo C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit
```

TemporaryDirectory 아래 합성 run.db/메모리 DB만 허용하고 종료 시 정리한다. 대상 편집·monkeypatch·개인 DB·네트워크·설치·commit 없음. 기존 19/28/5 probe 변경 없음. FIX-05의 fixture 및 CA03/04/07은 제외했다. 세 runtime 오류 수정 후 blocked 정상 경로를 먼저 재실행하고, 남은 binding/read 검증을 인수한다. D18 병행 방침은 유지하며 전체 최종 code REVIEW/VERIFY는 후속 새 세션 범위다.
