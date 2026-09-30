# GEMINI31-B-06 — 깨끗한 wheel 설치 테스트의 실제 실패

Gemini 3.1 Pro High B, HEAD `0edbea6f40dbc4bff18ba6fc9f554852b684494b` + B-05 미커밋. B packaging/테스트·handoff만. file read/write만; RunCommand/shell/git/tests/pip/web 호출 금지. 총괄 실행.

총괄이 B-05 코드로 R06/R08 42/42 PASS, wheel/sdist 실제 build PASS, 격리 venv에 wheel 설치 PASS. 그러나 그 venv의 python으로 `tests.test_packaging` 5개 실행에서 1 FAIL: `_check_strict_allowlist`가 tarfile의 디렉터리 항목 `investment_stack-0.1.0/.agents/skills/alternative-asset-analysis`를 금지 파일로 오판. tarfile.getmembers()의 isdir() 또는 해당 파일 여부로 디렉터리와 파일을 구분해 수정하라. 파일 허용목록은 정확한 8 이름×2 파일×원본/미러 경로만 허용해야 한다. 두 archive 필수 테스트를 유지한다.

추가 배포 경계: `MANIFEST.in`의 `recursive-include runtime *`는 runtime 아래 임의 credential 파일이 sdist에 들어갈 수 있다. 실제 runtime 자료가 `.py`뿐임을 총괄 확인했다. 승인된 `.py` 파일만 포함하도록 좁히고, 합성 `runtime` 내 금지 파일이 artifact에 들어가지 않는 검사를 해라. `setup.py`의 8 스킬 필수 파일 누락을 조용히 건너뛰는 `if os.path.isfile`도 빌드 실패로 바꿔라. 깨끗한 venv의 `sys.prefix/skills` 및 `.agents/skills`에 각 8개 SKILL.md/openai.yaml 원본/미러 byte equality가 실제 확인된 부분은 유지한다.

`handoffs/GEMINI31-B-06.md`에 위 재현 실패, 변경, 미실행 검증, 남은 Codex UI 인식 제한을 기록하라.
