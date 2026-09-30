# Handoff: GEMINI31-B-04 (wheel/sdist 빌드 실패와 허술한 검사 수정)

## 작업 정보
- **담당:** Antigravity Gemini `gemini-3.1-pro-high` (Headless mode)
- **Branch:** `codex/gemini31-b`
- **Worktree:** `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b`
- **Base Commit:** `5d66cc784ad6c617b8429ba33c06f0ef7beb3181`

## 이전 단계 빌드 오류 및 수정 내역
총괄의 `python -m build` 단계에서 발생한 `error: package directory 'runtime\\skills' does not exist` 에러와, 테스트가 `dist/` 폴더가 없을 때 스킵(skip)되어 검증을 제대로 수행하지 못하는 문제를 해결했습니다. 또한 배포본에 의도치 않은 파일이 섞이는(credential 누출 등) 보안 위협을 원천 차단했습니다.

1. **pyproject.toml 설정 충돌 수정 (빌드 에러 해결)**
   - 이전 작업에서 추가했던 `[tool.setuptools.packages.find]`의 `where = ["runtime", "."]` 및 `include` 설정이 `package-dir = {"" = "runtime"}`의 루트를 오버라이드하며 존재하지 않는 패키지 디렉토리를 참조하게 만들어 빌드 에러를 유발했습니다.
   - 해당 `where` 배열에서 `.`을 제거하고, 순수 파이썬 패키지(런타임) 탐색 범위(`investment_stack*`)로만 다시 좁혀 빌드 오류가 발생하지 않도록 되돌렸습니다.

2. **setup.py 데이터 허용 목록(Allowlist) 엄격화**
   - `os.walk`를 이용한 무조건 포함 로직은 향후 스킬 디렉토리에 실수로 포함될 수 있는 `.env`, 민감한 DB 파일 또는 검증되지 않은 새로운 임의의 파일을 배포 아티팩트에 포함시킬 위험이 큽니다.
   - 명시적으로 승인된 정확히 8개의 스킬(예: `investment-orchestrator`, `valuation` 등)과 정확히 2개의 대상 파일(`SKILL.md`, `agents/openai.yaml`)만 지정(Hardcode)하여, 불필요한 9번째 스킬이나 기타 파일이 유입될 수 없도록 allowlist 방식으로 제한했습니다.

3. **test_packaging.py 실증 검사(Fail) 강화**
   - `dist/` 디렉토리가 없거나 아티팩트가 없을 경우 `skipTest`로 넘어가던 허술한 검사 로직을 `self.assertTrue/fail`로 변경하여 빌드 전 검사 실행 시 반드시 실패(Fail)하도록 엄격하게 수정했습니다.
   - `zipfile` 및 `tarfile`로 읽은 배포본(wheel/sdist) 내부에 `personal.db`, `.env`, `run.db`, `workspace/runs` 등의 민감 패턴이 포함되지 않았는지 철저히 검사하는 네거티브 체크(Negative check)를 추가했습니다.
   - 단일 스킬이 아닌 허용된 8개 스킬 모두에 대해 원본/미러의 `SKILL.md` 및 `openai.yaml` 파일이 완전하게 패키징되었는지 반복문으로 꼼꼼히 확인하도록 Positive Check를 수정했습니다.

## 미실행 검증 및 남은 문제
- **헤드리스 제약 사항:** 시스템 제약에 의해 직접 셸/빌드 명령을 호출할 수 없으므로 실제 빌드의 성공 여부나 `tests`의 최종 통과 확인은 수행하지 못했습니다. 빌드와 테스트 실행은 총괄 단계에서 수행되어야 합니다.

## 총괄 실행 필요 명령 (검증용)
Coordinator 세션에서 이전과 동일한 다음 절차를 수행하여 빌드와 테스트 성공을 검증해 주십시오.

### 1. 패키지 재빌드
```powershell
python -m build --no-isolation
```
*(예상 결과: 이전의 `package directory 'runtime\\skills' does not exist` 에러가 해결되고 `dist/`에 새로운 `.whl`, `.tar.gz`가 생성됩니다.)*

### 2. 패키징 및 내용물 동적 검증 테스트
```powershell
python -m unittest tests.test_packaging -v
```
*(예상 결과: `test_built_artifacts_contain_skills` 테스트가 `.skip` 없이 `ok`로 성공하며, 이는 8개 스킬 전체 포함 및 민감 파일 배제 조건을 완벽하게 준수했음을 의미합니다.)*
