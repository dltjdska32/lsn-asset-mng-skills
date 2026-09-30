# GEMINI31-B-03 — 실제 wheel 검사의 R15 보완

- 담당: Gemini 3.1 Pro High B, branch `codex/gemini31-b`, 기준 HEAD `5d66cc784ad6c617b8429ba33c06f0ef7beb3181`. 소유 `pyproject.toml`, `MANIFEST.in`, `scripts/sync_agent_skills.py`, packaging 전용 테스트·인계; A/C 런타임, 공통 workflow 원본은 금지. 명령/셸/git/pip/테스트/웹 도구 호출 금지. 파일 read/write만; 총괄 실행.
- 총괄이 `python -m build --no-isolation`로 wheel/sdist 실제 빌드 성공을 확인했다. zip/tar 내부 민감파일 0, 런타임 포함. **둘 다 8개 skills 파일이 0개**다. 빌드 경고 `include LICENSE`는 파일 없음. 디자인 R15는 8개 원본 skills와 `agents/openai.yaml` UI metadata의 byte mirror, 깨끗한 wheel 설치 뒤 skill discovery, 민감파일 배포 제외를 요구한다. 기존 sync 스크립트는 SKILL.md만 검사한다.
- wheel/sdist 설치·repo checkout 사용 시 8개 스킬 원본과 UI metadata가 발견되고 서로 일치하도록 패키징/동기화 경로를 구체화하라. 실질 작동 확인 테스트를 작성하되 단순 MANIFEST 문자열 검사만으로 통과시키지 말라. 원본은 `skills/`이고 `.agents/skills/`는 미러다. 개인 데이터·로그·workspace·credential은 산출물에 포함하지 않는다. 불필요한 9번째 스킬이나 새 모드 만들지 않는다. LICENSE가 없으면 유령 include를 제거하거나 실제 확인 가능한 경로만 포함한다. 배포 안내 문서 최종 작성은 통합 뒤라 이 단계에서는 handoff로 인계.
- `docs/workflow/handoffs/GEMINI31-B-03.md`에 변경·실행하지 못한 검증·빌드 이전 증거와 남은 제한 기록. 총괄이 다시 wheel/sdist/설치/미러 검사를 수행한다.
