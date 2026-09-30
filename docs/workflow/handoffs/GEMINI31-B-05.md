# Handoff: GEMINI31-B-05 (통합 회귀와 배포 허용목록)

## 작업 정보
- **담당:** Antigravity Gemini `gemini-3.1-pro-high` (Headless mode)
- **Branch:** `codex/gemini31-b`
- **Worktree:** `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b`
- **Base Commit:** `0edbea6f40dbc4bff18ba6fc9f554852b684494b`

## 이전 단계 실패 컨텍스트 및 수정 내역
총괄의 통합 초안에서 기존 공통 테스트인 `tests/unit/test_r08_technical.py::test_trading_signal_gate_blocks_unauthorized_signals`가 `AVAILABLE`을 기대하여 실패(Fail)했습니다. 또한 `MANIFEST.in`의 와일드카드 선언(`recursive-include skills *`)으로 인해 의도치 않은 임의의 파일이 sdist에 포함될 수 있는 취약점이 지적되었습니다.

1. **기존 공통 테스트 수정 (회귀 실패 수정)**
   - R08 계약의 런타임 코드(`calculations/technical.py`)는 B-02에서 안전을 위해 무조건 fail-closed(`UNAVAILABLE`)를 반환하도록 고정되었습니다. 따라서 지표 계산이 정상적으로 이뤄지더라도 승인 게이트는 닫혀 있어야 합니다.
   - 런타임 코드는 수정하지 않고, `test_trading_signal_gate_blocks_unauthorized_signals` 내의 기존 단언(assertion)을 수정하여 `caller_approved=True`와 유효한 `approved_policy_id`가 주어져도 `UNAVAILABLE`과 `FAIL_CLOSED` 사유를 기대하도록 일치시켰습니다.

2. **MANIFEST.in 허용 목록(Allowlist) 엄격화**
   - `recursive-include skills *` 및 `recursive-include .agents *` 구문을 삭제했습니다.
   - 정확히 8개의 스킬에 대한 원본(`skills/`) 및 미러(`.agents/skills/`) 각각의 `SKILL.md`, `agents/openai.yaml` 파일만을 정확한 경로로 명시(총 32줄)하여 임의의 토큰/자격증명/덤프 파일 등이 sdist에 섞여 들어갈 수 없도록 원천 차단했습니다.

3. **test_packaging.py 실증 검사 강화**
   - Wheel 파일과 sdist 파일 중 하나만 있어도 통과하던 로직을 변경하여 **둘 다** 존재해야만 통과하도록 `assertTrue`를 각각 분리했습니다.
   - 아티팩트(`dist/`의 `.whl`, `.tar.gz`) 내부에 존재하는 `skills/` 또는 `.agents/skills/` 하위 파일이 정확히 `SKILL.md`와 `openai.yaml`로만 끝나는지 검사하는 화이트리스트 검열(`_check_strict_allowlist`)을 추가해 오염 방지를 증명했습니다.
   - 패키지 설치 이후 `sys.prefix`에 배포된 스킬 파일들의 실제 존재 여부와 원본-미러 간 Byte Equality를 동적으로 검증하는 `test_installation_target_skills` 메서드를 추가했습니다.

## 미실행 검증 및 남은 문제
- **헤드리스 제약 사항:** 이번 세션 역시 shell 도구 실행 권한이 없어 `python -m build`나 통합 테스트 스위트 전체를 직접 실행할 수 없었습니다.
- Codex UI에서의 실제 에이전트/스킬 인식 여부는 이 패키지 테스트 영역을 넘어선 것이므로 총괄 세션에서 별도로 확인해야 합니다.

## 총괄 실행 필요 명령 (검증용)
Coordinator 세션에서 아래 순서에 따라 테스트 및 빌드 결과를 확인해 주십시오.

### 1. 전체 통합 회귀 테스트
```powershell
python -m pytest tests/unit -v
```
*(예상 결과: `test_r08_technical.py`를 포함한 42개의 전체 테스트가 Fail 없이 통과해야 합니다.)*

### 2. 패키징 빌드
```powershell
python -m build --no-isolation
```

### 3. 설치 target 디스커버리 동적 검증
패키징된 `.whl`을 격리된 가상 환경(venv)에 설치한 후, 해당 가상 환경의 python을 통해 패키징 검사를 실행해야 `sys.prefix` 기반의 `test_installation_target_skills`가 실제로 검증을 수행합니다.

```powershell
# 예시: 격리된 venv 구성 후 설치
python -m venv venv_target
venv_target\Scripts\python -m pip install dist\investment_stack-0.1.0-py3-none-any.whl

# 설치된 venv의 인터프리터를 사용하여 패키징 검증 테스트 실행
venv_target\Scripts\python -m unittest tests.test_packaging -v
```
*(예상 결과: Wheel/sdist의 내용물 검열은 물론, 설치 경로(`sys.prefix/skills` 및 `sys.prefix/.agents/skills`)에 8개 스킬 원본과 미러 파일이 각각 존재하며 바이트가 정확히 동일함(Byte equality)을 입증하고 모든 테스트가 `ok`로 통과해야 합니다.)*
