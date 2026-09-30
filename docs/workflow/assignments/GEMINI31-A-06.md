# GEMINI31-A-06 — 새 반례 테스트의 실행 오류 수정

Gemini 3.1 Pro High A, HEAD `077ee538e13ff470900cb628ac3caa40ceee8581` + A-05 미커밋 변경. A 파일/인계만. 파일 read/write만; RunCommand/shell/git/tests/pip/web 금지. 총괄 실행.

총괄은 등록된 요청 정상 저장/reopen probe PASS, 미등록 유효 SHA 거부 PASS, 기존 관련 45/45 PASS를 다시 확인했다. 그러나 `tests.unit.test_contract_request_descriptors`는 import 시 `ModuleNotFoundError: No module named 'pytest'`로 0개 실행. 이 저장소는 unittest 표준이며 pyproject에 pytest가 없다. **신규 테스트를 unittest.TestCase + tempfile.TemporaryDirectory로 바꿔 표준 venv에서 실행 가능하게 하라.**

현재 파일은 `add_contract_evidence`에 진짜 `encode_envelope(MarketQuote(...))`가 아닌 손수 만든 불완전 dict를 넘기고, `manager.open()`이 예외를 던진다고 가정한다. `tests/unit/test_contract_storage_audit.py::test_positive_reopen_and_persistence`의 실제 DTO/사용법을 참고해 synthetic fixture를 유효하게 만들고, 실패는 정확히 기대한 경계에서 assertion하라. `manager.open()`은 `RunValidationReport.valid=False`를 돌려주는 경로임을 확인해 assertion을 맞추라. 정책 버전 반례도 먼저 정상 typed evidence를 등록한 후 정확한 DB metadata 변경을 쓰되 테스트끼리 독립 temp DB를 사용한다. 이전 A-05 기능은 유지. 새 인계 `handoffs/GEMINI31-A-06.md`에 수정/미실행 테스트/남은 갭을 짧게 기록하고 종료하라.
