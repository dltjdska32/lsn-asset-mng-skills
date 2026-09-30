# Handoff: GEMINI31-B-03 (실제 wheel 검사의 R15 보완)

## 작업 정보
- **담당:** Antigravity Gemini `gemini-3.1-pro-high` (Headless mode)
- **Branch:** `codex/gemini31-b`
- **Worktree:** `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b`
- **Base Commit:** `5d66cc784ad6c617b8429ba33c06f0ef7beb3181`

## 이전 단계 실패 컨텍스트 및 수정 내역
총괄의 두 번째 실행 검증에서 패키징(wheel/sdist) 아티팩트 내부에 민감 파일들은 잘 제외되었으나, R15 요구사항인 **8개의 원본 스킬 파일(`SKILL.md` 및 `agents/openai.yaml` UI metadata)**이 0개 포함되는 문제가 확인되었습니다. 추가로 존재하지 않는 `LICENSE` 파일에 대한 경고가 있었습니다.

해당 문제를 해결하기 위해 다음과 같이 패키징 경로와 동기화 스크립트를 구체화했습니다.

1. **MANIFEST.in 및 유령 LICENSE 정리**
   - 불필요한 빌드 경고를 없애기 위해 존재하지 않는 `include LICENSE` 라인을 `MANIFEST.in`에서 제거했습니다.
   - `recursive-include skills *` 및 `recursive-include .agents *` 규칙을 추가해 Source Distribution (sdist) 단계부터 파일이 포함되도록 명시했습니다.

2. **Wheel 파일 내 스킬 원본 포함 (setup.py)**
   - `pyproject.toml` 단독으로는 순수 파이썬 패키지(purelib) 외부의 루트 데이터 디렉토리(`skills/`, `.agents/`)를 wheel에 포함하기 어렵습니다.
   - 따라서 `setup.py`에 `data_files`를 사용하여 배포 시 sys.prefix (루트) 경로에 8개 스킬의 원본(`SKILL.md`, `agents/openai.yaml`)이 포함된 `skills/`와 미러 디렉토리인 `.agents/`가 함께 번들링되도록 구성했습니다.

3. **sync_agent_skills.py 업데이트 (UI Metadata 포함 미러링)**
   - 기존에는 `SKILL.md` 파일만 동기화/검사하도록 구현되어 있었습니다.
   - `agents/openai.yaml` UI 메타데이터도 함께 byte equality 검사 및 미러링 대상으로 포함되도록 동기화 로직을 구체화했습니다.

4. **test_packaging.py 동적 검증 추가**
   - 단순 정적 문자열 검사만이 아니라, 실제 `dist/` 내 생성된 `.whl` 파일(zip)과 `.tar.gz` 파일(tar)을 열람하여, 내부 경로에 `personal.db`나 `.env` 등이 없는 것을 재차 확인하고 `investment-orchestrator` 등의 스킬 파일(`SKILL.md`, `openai.yaml`)이 실제로 존재함을 증명하는 동적 테스트를 추가했습니다.

## 미실행 검증 및 남은 문제
- **헤드리스 제약 사항:** 현재 세션은 shell 및 외부 도구 실행 권한이 없어 `python -m build`나 패키징된 wheel 파일을 `pip install`하여 실환경에서 스킬이 discovery되는지 직접 실행해 보지 못했습니다.
- 통합된 패키지 배포 안내(Documentation) 작성은 아직 수행하지 않았으며, 향후 병합(통합) 이후 별도 단계에서 진행해야 합니다.

## 총괄 실행 필요 명령 (검증용)
총괄 (Coordinator) 세션에서 다음 명령어들을 순차적으로 실행하여 패키징을 수행하고 결과를 검증해 주십시오.

### 1. Agent Skills 미러링 및 검증
```powershell
# 변경된 스크립트로 스킬 디렉토리 동기화 및 검증
python scripts/sync_agent_skills.py
python scripts/sync_agent_skills.py --check
```
*(예상 결과: 원본 `skills/`와 `.agents/skills/`에 `SKILL.md` 뿐만 아니라 `agents/openai.yaml` 파일도 정상적으로 8개씩 동기화되어 있어야 합니다.)*

### 2. 아티팩트 빌드
```powershell
python -m build --no-isolation
```
*(예상 결과: `include LICENSE` 경고 없이 빌드가 완료되고, `dist/` 폴더 내에 sdist(.tar.gz)와 wheel(.whl) 파일이 생성됩니다.)*

### 3. 패키징 동적 검증 단위 테스트 실행
```powershell
# 생성된 wheel/sdist를 직접 분석해 민감정보 배제와 스킬 파일 포함 여부를 검증
python -m unittest tests.test_packaging -v
```
*(예상 결과: 새롭게 추가된 `test_built_artifacts_contain_skills` 테스트가 `.whl`과 `.tar.gz` 내부를 스캔하여 8개의 스킬(예: `investment-orchestrator`) 및 `.yaml` 데이터 파일이 있는지 확인하고 성공해야 합니다.)*
