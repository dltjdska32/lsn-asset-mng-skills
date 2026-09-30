# GEMINI31-B-README-01 — Windows 설치 안내 정확화

Gemini 3.1 Pro High B, B branch HEAD `fccbe84` 기준, R15/DESIGN-v0.1. 소유 `README.md`와 새 `docs/workflow/handoffs/GEMINI31-B-README-01.md`만. 파일 읽기/쓰기만, RunCommand/shell/git/tests/pip/web 금지. 이전 DOCS-01이 RunCommand denied로 미인수였음을 반복하지 말라.

README의 `The runtime has no third-party dependencies.` 문구는 pyproject의 Windows `tzdata`/`truststore>=0.9.1`와 충돌한다. 실제 의존성을 정확히 기술하고, Windows PowerShell venv 생성·활성화·**같은 venv interpreter**의 `python -m pip install -e .`, `python -m unittest discover -s tests -q` 및 skill mirror check를 쉽게 재현하는 설치 문장으로 `Run locally` 절만 수정하라. `python` 경로가 venv와 일치해야 한다. `skills/` source와 `.agents/skills/` repo-local mirror, `python scripts/sync_agent_skills.py --check`가 byte 동일성 검사임을 설명하라. wheel/sdist에 정확히 8개 스킬 × SKILL.md/openai.yaml × source/mirror가 들어가는 검증된 포장 범위를 쓰되, 설치 환경에서 Codex UI 자동발견까지 증명됐다고 단정하지 말라. 현재 repo-local Codex 세션 Available skills에서 8개 발견된 것은 확인됨. 기존 안전 경계/아키텍처·역사 기록 삭제 금지. 인계에 미실행 테스트를 적어라.
