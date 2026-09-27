# RC12 브리핑 영속·참조 결속 인계

- 요구사항 R14·R17. 독립 REVIEW-CODE-01이 기준 root `2b01ab3047cb1f22d1087099cda768c2aba2e316`에서 P2 RC12를 재현했다. 원 probe/출력은 `reviews/review_code_01_briefing_persistence_probe.py`와 `_output.txt`에 보존했다.
- 반례: 같은 run에서 두 번 렌더한 보고서의 5항목 브리핑이 개인 상태 결속에 따라 달라져도 report_ref와 section_refs가 같고, run.db에는 브리핑 본문/typed 근거가 없었다. 따라서 반환 ref만으로 과거 표시 내용과 갱신 변화를 재구성할 수 없었다.
- A 세션이 사용 한도 오류로 중단된 상태라 총괄이 A 소유 `execution/analysis_modes.py` 및 통합 테스트를 보정했다. 렌더된 브리핑과 typed `NonPostingBriefing`을 함께 canonical SHA-256으로 결속해 `final_briefing` report section에 고유 ID로 저장한다. 이번 report_ref manifest는 해당 section의 content_reference를 포함한다. 동일 run에서 브리핑이 바뀌면 새 ref가 발급되며 이전 브리핑 section은 덮어쓰지 않는다.
- 총괄 직접 검증: reviewer RC12 합성 probe **1/1 PASS**(브리핑 변화→서로 다른 ref/section refs, 저장된 두 section), equity 및 C 관련 집중 **11/11 PASS**, RC10-R2 manifest 경계 **10/10 PASS**. 개인 DB·주문 없음.
- 남은 검증: wheel/sdist 재빌드 뒤 전체 suite, 독립 reviewer 새 SHA에서 이전 브리핑 재조회 및 refresh fingerprint 검토, 다른 Codex 최종 검증. R08·13 판단 근거 결속 및 승인 정책에 따른 행동 규모는 미완이다.
