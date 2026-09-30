# GEMINI31-B-04 — wheel/sdist 빌드 실패와 허술한 검사 수정

Gemini 3.1 Pro High B, HEAD `5d66cc784ad6c617b8429ba33c06f0ef7beb3181` + B-03 미커밋 변경. B packaging/미러/전용 테스트·인계만 수정. 파일 read/write만, RunCommand/shell/git/tests/pip/web 금지. 총괄이 실행한다.

총괄이 8개 `agents/openai.yaml` 미러를 생성하고 `--check` PASS 확인한 뒤 B-03 코드를 `python -m build --no-isolation`로 실제 빌드했으나 **FAIL**: `error: package directory 'runtime\\skills' does not exist`. `[tool.setuptools.packages.find] where=["runtime", "."] include=["investment_stack*", "skills*", ".agents*"]`가 package-dir root와 충돌한다. `skills/`와 `.agents/`는 Python package가 아니다. 런타임 package 발견은 `runtime/investment_stack`으로 좁히고, 정확히 8개 SKILL.md + 8개 agents/openai.yaml 원본 및 미러만 wheel/sdist에 data로 넣어라. `setup.py`의 현재 `os.walk` 전체 파일 무조건 포함도 credential/임의 새 파일이 배포될 수 있어 위험하다. 하드코딩된 정확한 8개 이름/2파일 allowlist를 사용하고 원본/미러 byte 동일성을 확인한다. 개인 DB/log/.env/workspace는 포함 금지.

`tests/test_packaging.py` 동적 테스트가 `dist/` 없으면 skip하므로 실증 검사가 아니다. 테스트에 artifact 경로를 주입하거나 빌드 fixture를 만들고 없으면 fail하도록 변경한다. 8개 모두의 스킬/metadata와 민감 경계를 검사하라. 이 테스트는 빌드 성공/실제 결과를 보게 해야 한다. B-04 인계에 첫 빌드 오류·수정·미실행 검증·남은 제한 기록하고 즉시 답하라.
