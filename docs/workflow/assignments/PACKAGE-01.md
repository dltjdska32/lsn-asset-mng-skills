# PACKAGE-01 배정 (통합 API 확정 후)

Gemini B / gemini-3.8-flash-high high / codex/gemini-b worktree. REQ-v1 R15·16, DESIGN-v0.1/실행v0.2. 기준SHA·확정 CLI API는 총괄의 후속 실행 메시지로 전달하며 아직 실행 지시가 아니다.

소유: README.md·IMPLEMENTATION_STATUS.md·ARCHITECTURE.md, pyproject.toml·package data/build allowlist, skills/*/SKILL.md 및 같은 skill의 UI metadata, scripts/sync_agent_skills.py, 신규 tests/unit/test_r15_*.py, handoffs/PACKAGE-01.md. workflow 공유 문서는 총괄 소유. runtime code는 A/C/B 선행 소유권 유지. .agents mirror는 원본 변경 후 총괄이 스크립트로 동기화한다. Gemini shell/git/pip/web tools 금지, 파일 읽기/쓰기만.

확정 코드 동작을 직접 읽어 설명하며 아직 없는 기능/실증하지 않은 live/미검증 13F 가중치를 완료로 쓰지 않는다. 8개 스킬·7개 고정모드·DB분리 유지. chart/13F는 runtime 내부 연계, 미확정 개인정책 gate와 price stale 차단을 스킬/사용설명/UI에 일관되게 전달. design §10의 참조 방법 추적은 새 코드 경로와 실제 보류 이유로 검증하되 공유문서 편집 대신 인계에 추적 diff를 제출한다.

Windows 설치는 python -m venv, 같은 .venv/Scripts/python으로 pip/runtime/tests 실행, tzdata와 Windows truststore 조건부 의존성, config/package resources 위치, synthetic examples로 안내한다. truststore는 SSLContext(ssl.PROTOCOL_TLS_CLIENT) scoped 사용이며 검증 해제/전역 ssl 주입을 안내하지 않는다. deploy는 아직 로컬 package build/install 검증이며 원격 배포 완료라고 쓰지 않는다.

배포 산출물은 runtime 필수 파일/config/skills/UI만 allowlist로 포함하고 workspace/runs·DB·개인데이터·.env·logs·workflow세션 프롬프트·Git/worktree 캐시를 포함하지 않는다. wheel/sdist와 fresh isolated venv install 후 실제 CLI check/execute smoke 및 resource loading 테스트를 총괄이 실행할 명령으로 인계. 코드/contract/schema/config/skill 버전의 의미를 구분하고 필요 버전 변화는 근거와 호환성 영향 기록.

완료 조건: install/build package data 검증용 테스트·8 skill discovery·canonical/mirror byte equality·CLI 실제 예시와 제한 문서 일치. 본인 미실행 검증은 명시하고 소유 파일·API·기준SHA·후속 명령을 인계한다. 비밀번호/사용자 계정정보/개인DB를 fixture로 쓰지 않는다.
