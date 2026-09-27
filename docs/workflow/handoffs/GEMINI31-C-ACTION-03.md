# Handoff: GEMINI31-C-ACTION-03

- **작업 ID**: GEMINI31-C-ACTION-03
- **담당**: Antigravity Gemini 3.1 Pro High (Session C)
- **기준 HEAD (Base Commit)**: `f7d74653b093ef2b13980658bedd72b66bc1696e` (+ ACTION-01, 02 미커밋 수정분)

## 작업 내용 및 검토 결과

1. **조건부 수량 노출 차단 (안전 계약 보강)**:
   - `policy`에 전달되는 `approval_ref`나 `policy_version` 같은 문자열만으로는 검증된 Provenance/Registry 승인 결속을 증명할 수 없습니다. 따라서 현 단계에서는 계산된 거래 규모를 `ActionProposal.tranches`에 담아 외부로 유출하는 것을 전면 차단했습니다.
   - `calculate_action_proposal`은 규모 산출이 가능하더라도 무조건 `tranches=()`인 상태로 `WAIT`를 반환하며, 계산된 가상 규모와 비용은 `conditions` 문자열로만 덧붙여 기록(Logging)합니다. (A 도메인 및 검증 Registry 통합 전까지 방어)

2. **순수 Arithmetic 로직 분리 및 수수료 단위 명시 (`decisions/action.py`)**:
   - 예산 내 최대 매수 가능 수량(Lot 단위 내림)과 총비용을 계산하는 순수 산술 함수 `calculate_budget_arithmetic`을 별도로 분리했습니다. 
   - 수수료 항목을 단위당 수수료(`fees_per_unit`)로 명확히 정의하고, (단가 + 단위수수료) * 환율 * 수량 <= 예산 조건을 엄격히 증명하는 로직을 구축했습니다.
   - 이 분리된 함수의 계산 결과(`BudgetArithmeticResult`)를 임의로 실제 제안(Tranche)으로 승격시키지 않습니다.

3. **명시적 통화/FX 검증 도입**:
   - `currency` 단일 변수에 의존하거나 외부의 `requires_fx` 플래그를 믿는 대신, 가격 통화(`quote_currency`)와 예산 통화(`budget_currency`)를 직접 비교합니다.
   - 두 통화가 같으면 1:1로 취급하지만 다를 경우 반드시 검증된 `verified_fx`를 요구하고, 누락 시 엄격하게 `WAIT` (unavailable) 처리합니다.

4. **단위/합성 테스트 개선 (`tests/decisions/test_action.py`)**:
   - 모든 ACTION 제안의 `tranches` 길이가 0인지 단언(assert)하도록 테스트를 수정했습니다.
   - 계산된 산술 내역("Arithmetic evaluated BUY for 40 units...")이 `conditions` 문자열에 정상적으로 기재되는지 검증합니다.
   - 환율 검증 시 `quote_currency`와 `budget_currency`를 다르게 주입하여 실패/성공 여부를 테스트했습니다.
   - 분리된 `calculate_budget_arithmetic` 함수에 대한 단위 테스트(`test_pure_arithmetic`)를 추가해 단일 통화 및 교차 통화 환경에서의 Lot, 비용 계산 정확성을 검증했습니다.

## 테스트 명령어 (실행 요청)
- 총괄은 아래 명령어로 수정된 C 세션의 Action Proposal 테스트를 재실행하십시오. (Headless 제한으로 세션 C는 직접 실행하지 않았습니다)
```powershell
$env:PYTHONPATH = "runtime"
python -m unittest discover -s tests/decisions -v
```

## 남은 부분 (인계)
- 현재 의사결정 모듈의 예산 산술 로직 및 방어 제약은 완성되었지만, A 도메인의 가치평가 및 Provenance(승인) Registry 검증 체계와 연결되지 않았습니다. 
- 추후 통합 파이프라인이 완성되고 Registry 기반의 안전한 승인 증거가 주입될 때 비로소 `tranches` 배열을 개방(Open)하고 실제 의사결정(BUY/SELL) 상태를 활성화(Posting)할 수 있습니다.
