# 01 수신 코드 추가 독립 검토

독립 reviewer `/root/browser_patch_01_independent_review`가 01 수신 코드 고정 상태를 읽고 메모리 내 synthetic request/predictor stub으로 확인했다. Runtime/DB/문서 편집 없이 검토했고 실제 모델·시장 성능을 검증하지 않았다. 최종 수락 검토와 별개다.

## P1 Kronos 입력 데이터 결합 누락

`runtime/investment_stack/forecasting/adapters/kronos.py::forecast`, 93–114행. 요청 as_of/마지막 history timestamp는 `2020-12-31`, history 가격100인데 OHLCV index `2025-12-31`/close1000을 전달하면 날짜가 요청의 과거 시점으로 대체되고 값1000은 유지된다. Stub predictor 결과가 COMPLETE/point150으로 통과했다. 미래 또는 다른 데이터가 요청의 날짜로 재라벨링될 수 있다. 요청 timestamps/history/price basis와 OHLCV의 관측시점 및 close를 검증해야 한다.

## P1 앵커 기준시각 누수

`runtime/investment_stack/forecasting/ensemble.py::combine`, 103–119행 및 `engine.py::run`, 31–32행. 요청 as_of `2020-12-31`에 anchor.as_of `2021-01-31`/base200을 전달하면 PARTIAL/point약200을 생성하고 합성 anchor component.as_of를 요청날짜로 덮는다. 미래 앵커의 가격 근거가 과거 요청으로 사용된다. anchor 실제 기준시각과 요청의 허용 cutoff를 결합해야 한다.

## P1 CLI/Kronos 필수 입력 불일치

`scripts/run_pretrained_forecast.py::to_monthly`, 136–143행 및 main215행; `adapters/kronos.py::forecast`, 100–104행. CLI 월봉에는 OHLCV5열만 있는데 Kronos는 amount를 필수로 요구한다. 기존 target_semantics만 보정한 request에서도 amount 누락 ERROR이며 predictor가 호출되지 않았다. 원천 amount가 없는데 계산한 값을 실제 거래대금으로 위장해서는 안 된다. 원천자료/지원하는 proxy의 의미 및 한계를 분리하거나 UNAVAILABLE을 명시해야 한다.

03 수신 후 같은 재현조건으로 재검증하고, 남아 있으면 브라우저 구현 담당에게 구체적 후속 수정을 요청한다.
