# Handoff: GEMINI31-C-ACTION-01

- **작업 ID**: GEMINI31-C-ACTION-01
- **담당**: Antigravity Gemini 3.1 Pro High (Session C)
- **기준 HEAD (Base Commit)**: `f7d74653b093ef2b13980658bedd72b66bc1696e`

## 작업 내용 및 검토 결과

1. **Non-posting Action Proposal 기본 구조 구현 (`decisions/action.py`)**:
   - `InvestmentDecision` 의도에 따라 실제 행동 가능한 규모(Tranche)와 금액을 계산하여 `ActionProposal` 인스턴스를 반환하는 `calculate_action_proposal` 함수를 구현했습니다.
   - 주문 실행(posting/원장 writer)으로 이어지지 않도록 `non_posting=True` 제약을 명시했으며, 반환 상태는 향후 A도메인 계산 엔진 연계 완료 전까지는 임시로 항상 `WAIT`(대기) 상태를 유지하여 안전성을 보장합니다. (조건부 제안 텍스트만 발행)

2. **예산 및 매매 조건 계산**:
   - 승인된 안전마진(`m`)과 적격 가치(`V`)가 있을 때만 `entry = V * (1 - m)` 목표 진입가를 도출하고 가격이 이를 상회하면 대기(Wait for price <= entry)하도록 조건을 강제했습니다.
   - 매수(`BUY`/`ADD_BUY`) 시 가용 자금 산출은 `available_cash_after_buffer`, `concentration_headroom`, `approved_risk_budget` 세 가지 변수 중 최소값을 선택해 적용합니다.
   - 매매 수수료(`fees`)와 검증된 환율(`verified_fx`)을 합산한 실제 소요 비용 기준(`(price + fees) * fx_rate`)으로 예산을 나누고, `lot_size` 단위로 내림(`ROUND_DOWN`)하여 과매수 위험을 차단했습니다.
   - 매도(`SELL`/`REDUCE`) 시 검증된 처분 가능 수량(`disposable_quantity`) 한도 내에서만 규모를 제안합니다.

3. **데이터 불확실성 시 방어 로직**:
   - 미평가 자산/부채, 미결제 주문(pending orders)이 개인 상태에 포함되어 있거나, FX가 필요한데 검증된 환율이 없다면 즉시 정밀 규모 계산을 중단하고 `WAIT` 및 사유를 반환합니다.
   - 13F가 `UNVALIDATED` 상태이거나 차트 신호가 `UNAPPROVED`일 때 매수(`BUY`) 판단 입력으로 승격되는 것을 차단했습니다.

4. **단위/합성 테스트 추가 (`tests/decisions/test_action.py`)**:
   - 정책/가격/개인 pin 누락 시 거부, 3개 예산 제약 각각 지배 시나리오, 환율 결측, fees 및 lot 내림, 매도 수량 초과 상한 차단, 13F/차트 미승인 무시 시나리오 등을 커버하는 합성 테스트를 추가했습니다.

## 테스트 명령어 (실행 요청)
- 총괄은 아래 명령어로 C 세션의 Action Proposal 테스트를 실행하십시오. (Headless 환경 정책에 따라 C 세션은 직접 테스트를 실행하지 않았습니다)
```powershell
$env:PYTHONPATH = "runtime"
python -m unittest discover -s tests/decisions -v
```

## 남은 부분 (인계)
- 본 작업은 "의도된 행동(BUY, SELL)"이 외부에서 주어졌을 때 정책에 맞게 예산과 규격을 짜맞추는 '선행 API (수직 슬라이스)'입니다.
- Domain A의 가치 평가 모델, 최종 매수 의사결정 알고리즘 및 통합 파이프라인이 완성되어야만 `calculate_action_proposal`이 실제 입력과 통합될 수 있으며, 현재는 개별 단위로만 존재하므로 최종 리포트의 완성으로 간주되지 않습니다.
