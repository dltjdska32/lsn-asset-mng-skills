# GEMINI31-A-FALLBACK-04 — 실제 미수정 테스트 helper 한 곳

Gemini 3.1 Pro High A, 같은 worktree/대화, HEAD `962930d` + FALLBACK-01~03 WIP. **이번에는 `tests/unit/test_r05_fallback_eligibility.py`의 `_obs` 함수와 새 `handoffs/GEMINI31-A-FALLBACK-04.md`만 수정.** 파일 도구만, RunCommand/shell/git/tests/pip/web 금지.

FALLBACK-03 인계는 sentinel로 구분했다고 썼지만 실제 파일에는 여전히 `def _obs(... obs_at: str | None = None)`와 `observed_at=obs_at or default_obs_at`가 남아 있다. 총괄 직접 재실행 14개 중 **동일한 1 FAIL**: `test_fundamentals_skip_missing_observation_time`, expected p2 got p1. 이 helper의 기본값을 module-level 고유 sentinel로 하고, `obs_at is sentinel`일 때만 default ISO 시각을 사용, `obs_at is None`이면 ProviderObservation.observed_at=None을 그대로 전달하라. 수정 후 `test_fundamentals_skip_missing_observation_time` 호출이 실제 None을 생성하는지 코드로 확인하라. 인계에는 변경된 helper 본문 핵심 한 줄을 적고, 직접 테스트를 실행하지 않았다고 기록하라. 이 단일 실패 외 코드/테스트를 변경하지 말라.
