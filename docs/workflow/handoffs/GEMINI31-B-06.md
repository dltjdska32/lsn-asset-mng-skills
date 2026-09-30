# Handoff: GEMINI31-B-06 (깨끗한 wheel 설치 테스트의 실제 실패 수정)

## 작업 정보
- **담당:** Antigravity Gemini `gemini-3.1-pro-high` (Headless mode)
- **Branch:** `codex/gemini31-b`
- **Worktree:** `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b`
- **Base Commit:** `0edbea6f40dbc4bff18ba6fc9f554852b684494b`

## 이전 단계 실패 컨텍스트 및 재현
총괄의 R06/R08 테스트와 wheel/sdist 빌드, 그리고 가상 환경(venv) 설치까지 모두 PASS했으나, 설치된 venv 환경에서 `python -m unittest tests.test_packaging` 실행 시 1건의 Fail이 발생했습니다.
- **오류 내용:** `_check_strict_allowlist` 메서드가 tarfile을 검사할 때 디렉터리 항목(예: `investment_stack-0.1.0/.agents/skills/alternative-asset-analysis`) 자체를 금지된 파일로 오판하여 검증이 실패했습니다.
- **보안 취약점 지적:** `MANIFEST.in`에서 `recursive-include runtime *`로 지정된 범위가 너무 넓어, `runtime` 내부에 임의의 credential 파일 등이 있을 경우 배포본에 포함될 위험이 존재했으며, `setup.py`에서 누락된 스킬 파일(8개 미만)을 조용히 건너뛰어 배포할 수 있는 취약점이 발견되었습니다.

## 수정 내역

1. **테스트 내 디렉터리 오판 해결 및 런타임 검열 추가**
   - `test_packaging.py`에서 `zipfile.infolist().is_dir()` 및 `tarfile.getmembers().isdir()` 메서드를 활용해 파일과 디렉터리를 엄격히 구분하도록 수정했습니다. 디렉터리가 아닌 실제 파일만 스킬 데이터 허용 목록(`SKILL.md`, `openai.yaml`)의 적용을 받습니다.
   - 아티팩트(sdist 및 wheel) 내부에 `runtime/` 혹은 `investment_stack/` 하위로 포함된 모든 파일이 오직 승인된 파이썬 스크립트(`.py`) 확장자인지 확인하는 네거티브 체크(Negative check)를 추가해, 합성된 금지 파일이나 더미 파일이 artifact에 스며드는지 검사하도록 강화했습니다.

2. **MANIFEST.in 범위 축소**
   - `recursive-include runtime *`를 `recursive-include runtime *.py`로 축소해, 런타임 하위 경로에서 오직 `.py` 파일만 sdist에 배포되도록 수정했습니다.

3. **setup.py의 조용한 실패(Silent Failure) 차단**
   - `if os.path.isfile(...)`로 단순히 존재할 때만 리스트에 넣고 없으면 넘어가던 로직을 제거했습니다.
   - 지정된 8개의 스킬(원본 및 `.agents` 미러)에 대해 필수 파일(`SKILL.md` 및 `openai.yaml`)이 하나라도 누락되어 있다면 즉시 `FileNotFoundError`를 발생시켜 배포/빌드 단계가 강제 실패하도록 엄격히 수정했습니다.

## 미실행 검증 및 남은 제한
- **헤드리스 제약 사항:** 시스템 제약에 의해 직접 venv를 생성하거나 `python -m build`, 테스트 스위트를 호출할 권한이 없으므로 직접적인 테스트 패스 여부는 재차 총괄에 위임됩니다.
- **Codex UI 인식 제한:** 실제 Antigravity Codex UI에서 8개의 스킬 메타데이터를 UI로 완전히 디스커버리하고 인식하는지 여부는 이 패키징 단위 테스트 범위를 넘어서는 기능이므로, 통합 후 총괄의 후속 확인으로 남겨두었습니다.

## 총괄 실행 필요 명령 (검증용)
총괄 (Coordinator) 세션에서 이전과 동일하게 아래 순서대로 패키지 재빌드와 테스트를 구동하여 수정된 테스트의 PASS를 확인해 주십시오.

### 1. 패키징 빌드
```powershell
python -m build --no-isolation
```
*(예상 결과: `setup.py`에 의해 8개의 스킬 원본과 미러 파일(총 32개)이 누락 없이 존재하면 정상 빌드됩니다.)*

### 2. 가상 환경 내 동적 패키징 검증
```powershell
# 이전에 구성된 대상 venv에 다시 패키지를 강제 재설치
venv_target\Scripts\python -m pip install --force-reinstall dist\investment_stack-0.1.0-py3-none-any.whl

# 테스트 실행
venv_target\Scripts\python -m unittest tests.test_packaging -v
```
*(예상 결과: 디렉터리를 불법 파일로 오인하던 오류가 해결되어 5개의 테스트가 모두 `ok`를 반환해야 합니다.)*
