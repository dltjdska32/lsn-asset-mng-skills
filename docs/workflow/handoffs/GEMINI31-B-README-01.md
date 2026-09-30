# Handoff: GEMINI31-B-README-01 (Windows 설치 안내 정확화)

## 작업 정보
- **담당:** Antigravity Gemini `gemini-3.1-pro-high` (Headless mode)
- **Branch:** `codex/gemini31-b`
- **Worktree:** `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b`
- **Base Commit:** `fccbe8428fdc9a125273dab1bd5b4cf99d1bfe4e`

## 변경 내역
- **README.md의 의존성 표기 수정:** 기존 `The runtime has no third-party dependencies.` 문구를 삭제하고, Windows 플랫폼용 실제 의존성인 `tzdata`, `truststore>=0.9.1`가 필요함을 정확히 명시했습니다.
- **Windows PowerShell 기반 설치 절차 갱신:** 임시 PYTHONPATH 스크립트 기반의 가이드를 제거하고, 동일한 `venv` 인터프리터 내에서 가상 환경 생성(`python -m venv venv`), 활성화(`Activate.ps1`), 패키지 설치(`python -m pip install -e .`), 단위 테스트(`unittest discover`), 스킬 바이트 동기화 검사(`sync_agent_skills.py --check`)를 차례로 수행할 수 있도록 재작성했습니다.
- **스킬(Skills) 디스커버리 및 패키징 경계 문서화:** `skills/` 원본과 `.agents/skills/` 복제본의 Byte-equality 구조를 설명하고, 패키징 시 정확히 8개의 스킬(총 32개 파일)만 허용되며 임의 파일은 차단됨을 명시했습니다.
- **UI 자동 발견 유보 명시:** 로컬 저장소 환경 내의 Codex 세션(Available skills)에서는 8개 스킬이 정상 발견되었음을 알림과 동시에, 타 환경에서 wheel 설치 후 Codex UI 자동 발견이 보장되는지에 대해서는 아직 실증되지 않았다고 분명하게 단서를 달았습니다.
- 기존의 아키텍처, 안전 경계, 역사적 기록 등은 모두 안전하게 보존되었습니다.

## 제한 사항 및 미실행 검증
- **헤드리스 제약 사항:** 시스템 제약에 의해 직접 셸 명령(git, pip, tests 등)을 호출할 권한이 없습니다. 따라서 새롭게 작성된 README의 설치/테스트/검증 명령(`pip install`, `unittest`, `sync_agent_skills.py --check`)을 이 세션에서 실제로 수행해 보지는 못했습니다.
- **총괄(Coordinator) 이관:** 총괄 단계에서 새로 기재된 Windows PowerShell 명령어를 복사하여 실제 환경에서의 원활한 설치 및 테스트 진행 여부를 점검해 주십시오.
