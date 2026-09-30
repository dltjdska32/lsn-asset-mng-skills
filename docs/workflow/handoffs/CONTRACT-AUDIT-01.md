# CONTRACT-AUDIT-01 인계

- 판정: **CHANGES_REQUIRED / 계약 인수 보류**. P0 미확인. 알려진 import/API 오류 외 추가 P1 7건(CA01–CA07).
- 고정 검토 SHA: `73d376e32437bf78f8534d040c68db106e59acb7`.
- 검토 폴더: `C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit`만 사용. root/Gemini A 최신 작업폴더는 검토하지 않음.
- 보고서: `C:/Users/lsn/Documents/Codex/2026-09-23/investment-contract-review/outputs/CONTRACT-AUDIT-01.md`.
- 인계: `C:/Users/lsn/Documents/Codex/2026-09-23/investment-contract-review/outputs/CONTRACT-AUDIT-01-HANDOFF.md`.
- 재현 코드: `C:/Users/lsn/Documents/Codex/2026-09-23/investment-contract-review/outputs/CONTRACT-AUDIT-01-probes.py`. 현 고정 SHA 실행: 18 FAIL/1 BLOCKED(manager import)/0 PASS. 부정 경계 감사 probe 결과이며 전체 suite 수치가 아님.

회송 핵심:

1. Trusted source normalizer가 만든 canonical evidence payload와 binding의 값·단위·기간·종목·공개시점·변환·eligibility를 모두 검증. evidence/hash의 존재만으로 승인하지 말 것.
2. 계산은 실제 참조 snapshot을 읽어 전체 binding을 비교. 과거 hash와 현재 slot 비교 금지.
3. 문자열 'false'→True 승인/완료 우회, wrong nested kind, unknown enum/date, bool→int coercion 차단.
4. gate와 계산 연결. 미승인 투자정책은 CONDITIONAL로 우회하지 않으며 unavailable output의 numeric payload도 통제.
5. invalid raw fact의 보존/생성은 허용. raw collection과 normalized/eligible 집합을 구분하여 invalid revenue가 covered로 승격되지 않게 한다. 정상 다른 metric의 부분 결과는 유지. 실제 기간 coherence 알고리즘은 후속 evaluator 담당.
6. unsupported/null/손상 ledger, 잘못된 active pointer는 reopen/read 시 fail-closed. 최신 counter/hash·run·scope·binding 전수 검증.
7. adapter normalized value/raw unit 불일치, Bar 가격 단위 SHARES, 13F quantity type/공개구간/voting 소실, 근거 없는 1000 scale default 수정.

다중종목 active key(purpose-only) 문제는 총괄이 CONTRACT-FIX-02에 포함했다고 회신했다. 수정 중인 새 코드의 해결 여부는 미검증.

자체 검증: Python 3.14.6 -X utf8 -B의 순수 메모리 probe. contracts 단독 import 성공, decoder/gate/domain/adapter 반례 실제 재현. manager는 MAX_PAYLOAD_BYTES ImportError로 막혀 SQLite 저장·CAS·rollback·reopen은 실행하지 않았다. ProviderObservation roundtrip도 observation_id TypeError로 중단되어 그 경로의 의미 보존은 정적 판단으로 구분했다. monkeypatch 우회 없이 원본 스냅샷을 검토했다.

안정된 B/C 착수 조건은 보고서 §5에 분리했다. strict/lossless DTO·scope·raw/normalized/eligible 분리, trusted canonical payload와 full binding 검증 facade, read/reopen fail-closed, gate/output 참조의 공통 테스트 및 새 commit이 먼저다. A의 source mapping/정정 선택/YTD·TTM/fallback evaluator와 B/C source별 분석 알고리즘 완성까지 기다릴 필요는 없지만, 미구현 evaluator 입력은 unavailable로 닫혀야 한다.

허용된 세 산출물 외 파일 변경, 코드 수정/commit/push, 개인 DB/네트워크 접근 없음. 수정 후 새 SHA에서 임시 run DB 회귀와 전체 contract suite 재실행 필요. 이후 REVIEW-CODE/별도 VERIFY는 그대로 후속 단계다.
