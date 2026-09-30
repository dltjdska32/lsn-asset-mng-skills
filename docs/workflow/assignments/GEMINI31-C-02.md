# GEMINI31-C-02 — 브리핑 계약 해석·안전성 수정

- 담당: 동일 Gemini 3.1 Pro High C 대화, branch `codex/gemini31-c`, 기준 HEAD `006b2b09de5fed2dfffbd8c6c52703d44963210b`와 C-01 미커밋 변경. C-01 소유 파일만. shell/git/테스트/웹 금지; 총괄이 실행한다.
- 총괄이 `tests/decisions` 4/4 실행했으나 설계 불일치를 발견했다. design.md 6장의 **브리핑 고정 5단계는 다섯 투자 등급이 아니라 다섯 출력 섹션**이다: ①지금 판단 ②가격·행동 표 ③핵심 근거 ④판단 변경 조건 ⑤상세 근거. C-01의 `STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL` 5등급 해석과 report builder가 한 줄 등급만 표시하는 것은 요구 불일치다. 원 설계의 판단값은 신규 매수/추가매수/보유/대기/축소이며 핵심 입력 부재는 대기/판단 보류다. 근거 없는 임시 `HOLD`를 `AVAILABLE`로 반환하지 말고 해당 판단을 보류하고 정확한 availability/reason을 표기한다. BRIEF 전체가 A 계산 전까지 미완임을 유지한다.
- `SelectedInputSet.verify_hash()` 또는 계산 lineage 실패는 단순 `PARTIAL` + 그대로 `verified_hash` 반환으로 위장하지 말고 결속 실패로 거부/UNAVAILABLE 처리한다. 모든 CalculationRecord가 동일 run/snapshot의 승인된 bound slots에 묶이는지 실제 확인하고, 빈 calculations 및 `has_price/has_policy/has_personal_snapshot` 단순 bool만으로 검증된 데이터가 있다고 선언하지 않는다. 값·단위·통화의 무조건적 일치도 요구하지 말고 각 계산의 의미 있는 차원/변환 경계만 확인한다.
- report builder 실제 output에 5섹션이 순서대로 나타나도록, 사용 가능한 입력에 한해 작성하되 미확정 셀에는 `계산 불가: 이유`를 쓴다. 본문 내부 ID 노출 금지, 상세 근거에만 ID. 필요하면 전체 브리핑을 선행 계약/구조로 한정하고 현실적으로 미구현인 최종 판단/규모는 unavailable로 둔다. 합성 테스트를 새 요구에 맞춰 고친다.
- C-02 인계에 실제 수정, 4/4이 왜 충분치 않았는지, 미실행 테스트와 남은 부분을 기록한다.
