# GEMINI31-B-07 — sdist egg-info 오판 수정

Gemini 3.1 Pro High B, HEAD `0edbea6f40dbc4bff18ba6fc9f554852b684494b` + B-05/B-06 미커밋. B packaging tests/인계만. file read/write only; RunCommand/shell/git/tests/pip/web 금지.

B-06 실제 wheel/sdist 빌드 PASS. 격리 venv wheel 강제 재설치 PASS, 설치 `sys.prefix` 8개 skills 원본/미러 byte equality 테스트 PASS. 하지만 `tests.test_packaging` 5개 중 archive 검사 1 FAIL: `_check_strict_allowlist`가 sdist의 정상 setuptools metadata 경로 `investment_stack-0.1.0/runtime/investment_stack.egg-info/PKG-INFO`를 runtime Python 소스 파일로 오판해 `.py` 아니라고 거부한다. 검사 경계를 `runtime/investment_stack/` **디렉터리 안 실제 패키지 소스**로 한정하고 `runtime/investment_stack.egg-info/`는 명시적으로 허용되는 빌드 metadata로 분리해라. 임의 비-Python 파일이 `runtime/investment_stack/`에 포함되는 것은 계속 거부. 디렉터리/파일 구분과 skills 32파일 허용목록도 유지한다. 빈 archive/한쪽 누락은 실패 유지.

수정·재현 실패·미실행 검증을 `handoffs/GEMINI31-B-07.md`에 기록. 총괄이 다시 실제 빌드 아티팩트 테스트를 실행한다.
