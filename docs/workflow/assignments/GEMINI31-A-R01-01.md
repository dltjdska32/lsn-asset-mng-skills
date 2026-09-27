# GEMINI31-A-R01-01 — 현재가 소비의 최소 안전 수직 경로

Gemini 3.1 Pro High A, branch `codex/gemini31-a`, HEAD `d6ef79bc90bb08f0bd170b37653c65a927b029b3`. 앞선 넓은 DOMAIN-01은 RunCommand headless 거부로 **코드 변경 없이 중단**됐다. 이번은 R01 한 항목만 처리. **ReadFile/ReplaceFileContent/WriteFile만 사용. RunCommand·shell·git·tests·pip·web 절대 호출하지 마라.**

소유 `runtime/investment_stack/deep_research.py`, A 전용 `tests/unit/test_r01_price_binding.py`, `handoffs/GEMINI31-A-R01-01.md`만. `deep_research.py::_current_price`는 현재 `UNKNOWN/UNAVAILABLE`만 차단하고 `STALE` 선택은 그대로 numeric current_price로 계산에 넘긴다. 또한 선택 관측의 instrument/currency/metric과 저장된 selected evidence binding이 맞는지 확인할 필요가 있다. 정상 FRESH 적격 선택만 current_price로 반환하고 STALE/UNKNOWN/UNAVAILABLE/future/종목 불일치/통화 불일치/관측시각 부재는 None 및 이유를 호출자가 전달할 수 있게 하라. `provider_results` 원시 배열로 다시 선택하지 않는다. 실제 `analyze` 경로에서 market_cap/valuation_input으로 잘못된 가격이 공급되지 않는 테스트를 표준 unittest synthetic fixture로 추가한다. 기존 API 호환 불가가 있으면 우회하지 말고 인계. R02–05/R09는 후속.

인계에 변경·미실행 검증·남은 범위·기준 HEAD를 적고 즉시 멈춰라.
