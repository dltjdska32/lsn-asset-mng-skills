# CODEX-C-FIX-01 인계

- 작업: C 담당 13F 안전성 수정 및 두 테스트 실패 정합화
- 요구사항: REQ-2026-09-23-v1 R12, R13, R16
- branch: `codex/luna-c`
- 시작 HEAD: `377dbb4e7c3f29bfd011c049acf4dd9dd98def0f`
- 구현 커밋: `c6a4431` (`fix 13F coverage and trade gate safeguards`)
- 기준 업무: `IMPL-C-FIX-03.md`; 시작 시 작업 트리 깨끗함

## 변경

- `tests/unit/test_r12_sec_13f.py`: filing date가 없는 문서와 두 누락행을 한 fixture에서 검사한다. `MISSING_FILING_DATE`/불확실 scale, 원시 값 보존에 따른 eligible total 0, 행별 누락 경고 두 개 및 집계 coverage 경고를 각각 확인한다. 행 부재만으로 매도를 선언하지 않고 비교 coverage `PARTIAL`과 `NOT_REPORTED`가 전파되는지 검사한다.
- `runtime/investment_stack/institutional/compare.py`: 부분 coverage에서 부재 종목은 계속 `NOT_REPORTED`로 처리한다. 유효 enum에 없는 `NoticeStatus.INCOMPLETE`를 참조해 비교가 예외로 중단되던 오류를 제거했다. 공식 filing notice는 `NoticeStatus`로, 누락/불완전 coverage는 비교 결과 `coverage_status`로 각각 표현한다.
- `tests/unit/test_r13_validation.py`: synthetic `score_status="VALIDATED"` report와 문자열 approval을 함께 전달해도 gate가 `DISABLED`이고 `approval_ref`/`validation_ref`를 발명하지 않는 음성 테스트로 교체했다.

## 실행 검증

- 통과: 지정 테스트 모듈 전체, 26개 (`tests.unit.test_r12_sec_13f`, `tests.unit.test_r13_validation`), Python 3.14 및 총괄 환경의 `tzdata` 사용. 대상 worktree의 `runtime`을 `PYTHONPATH`로 지정해 `unittest` 실행.
- 포함 검증: unknown/invalid vintage scale 제한, 누락행 및 partial coverage, absence != sold, confidential omission, amendment cutoff invariance, split/quantity comparability, synthetic validation/approval trade gate 거부.
- 통과: `git diff --check`.
- `python -m pytest`는 시스템 Python에 pytest가 없어 실행할 수 없었다. 지정 `unittest` 실행은 전체 26개 성공.
- SEC archive XML live E2E는 실행하지 않음. 이전 작업 인계에 SEC archive HTTP 403이 기록되어 있으며 이 변경으로 live 수집이 검증된 것은 아니다.
- 전체 repository suite 및 A/B 소유 테스트는 실행하지 않음.

## 잔여 사항

- 13F 점수의 실증 backtest, holdout, 거래비용 평가 및 공식 governance 승인 자료가 없어 trade gate는 계속 `DISABLED`다. A 작업의 trusted typed gate context 연결은 별도 후속 통합이다.
- 실 SEC XML의 접근·버전별 동작은 미확인이다. 이 커밋은 합성 fixture와 기존 공개 사본 테스트만 검증했다.
- 개인 DB, 인증정보, 주문 경로, 원격 push/deploy를 사용하지 않았다.
