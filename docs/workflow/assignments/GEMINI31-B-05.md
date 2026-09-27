# GEMINI31-B-05 — 통합 회귀와 배포 허용목록

Gemini 3.1 Pro High B, HEAD `0edbea6f40dbc4bff18ba6fc9f554852b684494b`; B 전용 파일·`handoffs/GEMINI31-B-05.md`만. shell/git/tests/pip/web 도구 호출 금지, file read/write만. 총괄이 실행한다.

총괄의 통합 초안에서 B 담당+기존 R06/R08 테스트 42개 중 1 FAIL: `tests/unit/test_r08_technical.py::test_trading_signal_gate_blocks_unauthorized_signals`가 임의 `caller_approved=True` + `approved_policy_id`로 `AVAILABLE`을 기대한다. 승인 registry가 없는 실제 R08 계약에서는 이 기존 assertion이 낡았다. **실행 코드를 다시 열지 말고** 테스트를 fail-closed 기대에 맞춰 고쳐라. 공인 지표 계산과 거래 신호 사용 가능성을 혼동하지 않는다.

B-04 wheel/sdist 실제 빌드 및 격리 target 설치 PASS, 8개 skills 원본/미러 SKILL.md+openai.yaml 각각 확인, 민감 패턴 0, B 신규16/16 PASS. 하지만 `MANIFEST.in`의 `recursive-include skills *` 및 `.agents *`는 sdist에 임의 새 토큰 파일을 끌어들일 수 있다. 정확히 8개 스킬×SKILL.md/openai.yaml×원본/미러 파일만 허용목록에 넣고 임의 추가 파일이 sdist/wheel에 들어가지 않게 하라. `tests/test_packaging.py`는 wheel **또는** sdist 하나만 있으면 통과하는 것을 둘 다 필수로 고치고, 설치 target의 `.agents/skills` 파일 존재/byte equality를 실제 검사할 수 있게 하라. 필요한 경우 추가 파일 오염 반례를 합성 build fixture로 검증하되 개인 자료 사용 금지. repo-local discovery를 확인할 설치 target 경로와 같은 interpreter 사용법을 인계에 명시하라. Codex UI 실제 인식은 총괄 후속 확인으로 별도 남긴다.

공통 A/C 파일은 편집하지 않는다. 변경·미실행 검증·한계·기준 SHA를 handoff에 남기고 즉시 응답한다.
