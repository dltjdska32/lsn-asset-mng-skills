# GEMINI31-C-03 — 브리핑 계산 결속과 실제 렌더링 검증

- 담당 Gemini 3.1 Pro High C, branch `codex/gemini31-c`, 기준 HEAD `2b772fd584942d70636645958be1f020d879014d`. 소유 `decisions/**`, `reporting/**`, C 전용 테스트 및 `handoffs/GEMINI31-C-03.md`. 명령/shell/git/tests/pip/web 금지, 파일 read/write만. 총괄이 테스트한다.
- 총괄이 C-02 담당 4/4 및 기존 보고서 회귀25/25 PASS를 실행했으나 새 5섹션이 `InvestmentReportBuilder.build`의 실제 마크다운에서 원하는 순서·ID 경계로 나오는 전용 테스트가 없다. 합성 run DB와 review fixture로 builder 실제 output을 검증하라. 본문에 내부 ID를 뿌리지 말고 상세 근거에만 둔다.
- `generate_briefing`은 `calc.verify_lineage()`와 run_id만 확인한다. 계산의 `selection_snapshot_hash == inputs.snapshot_hash`와 bound slot의 입력값/단위/통화/evidence_id/fingerprint가 실제 SelectedInputSet의 같은 slot에 해당하는지 검증해 다른 선택본의 유효 계산을 혼용하지 않는다. 오류는 UNAVAILABLE/INCONCLUSIVE. bool `has_price/has_policy/has_personal_snapshot=True`만으로 검증된 가격·정책·개인 상태가 있다고 주장하는 문구를 출력하지 않는다. A 도메인 결과와 승인 정책/개인 pin 연결 전까지 최종 매수·규모 판단은 명시적으로 보류한다. 기존 임의 HOLD/가짜 시세 재도입 금지.
- 변경 및 미실행 검증, 남은 Domain A 연계를 인계하라.
