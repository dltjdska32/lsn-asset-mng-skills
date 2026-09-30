# GEMINI31-B-02 — 첫 구현의 실패 테스트·신호 게이트 수정

- 담당: 동일 Gemini 3.1 Pro High B 대화, branch `codex/gemini31-b`, 기준 HEAD `07e8b0be876da7635e1c2c0bdbc040acbd04970c`와 B-01 미커밋 변경. 소유 파일은 B-01과 동일. shell/git/테스트/웹 금지; 총괄이 실행한다.
- 총괄의 첫 실행에서 `tests/providers/test_b*.py` 8/8, `tests/test_packaging.py` 3/3은 통과했지만 `tests/calculations/test_b_technical.py` 4개 모두 오류였다. `_mock_bar`가 `PublicAvailability.unknown("")`을 호출했으나 API는 키워드 전용 `locator=None`이다. fixture를 실제 계약에 맞춰 수정한다.
- 더 중요한 안전 결함: `evaluate_signal_gate(..., caller_approved=True, approved_policy_id="POLICY_123")`의 임의 문자열만으로 `AVAILABLE/POLICY_EVALUATED`가 된다. design C/R08은 명시적으로 검증·승인된 위험 정책과 파라미터가 없는 상태에서 거래 신호를 만들지 않도록 요구한다. 승인 registry가 없는 현재 구현에서는 외부 bool/문자열을 신뢰하지 않고 fail-closed로 유지한다. 임의 정책 ID로 AVAILABLE을 기대하는 테스트는 제거하고, 같은 입력이 UNAVAILABLE임을 검증한다. 지표 계산은 계속 가능하다. 승인 체계를 새로 상상해 만들지 않는다.
- 패키징은 정적 문자열 검사만으로 통과를 주장하지 않는다. `MANIFEST.in`, `pyproject.toml`, 미러 스크립트를 검사해 source/wheel 설치 후 런타임·8 skills 구성이 실제로 맞는지 총괄에게 검증 명령/예상 내용을 인계하라. 총괄이 artifact 빌드와 검사 수행. 개인 DB·인증정보 금지.
- B-02 인계에 변경·미실행 검증·남은 문제 및 첫 실패를 기록한다.
