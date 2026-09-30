# FINISH-REPORT-STATUS-01 인계

- 기준 소스: `53b6be01f45ad5b57e8d0718b270f4a14fe01649` (`codex/autonomous-integration`).
- 소유 파일: `runtime/investment_stack/reporting/builder.py`, `runtime/investment_stack/execution/analysis_modes.py`, `tests/unit/test_phase6_report_review.py`.
- 독립 검토가 같은 본문을 가진 섹션의 상태가 AVAILABLE에서 PARTIAL로 바뀔 때 기존 내용 주소 참조가 재사용되어 과거 행의 상태가 덮어써지는 P2 반례를 재현했다.
- 내용 주소 계산에 섹션 상태를 포함하고, 분석 모드가 조회한 섹션 행도 저장된 상태와 정확히 일치해야 manifest에 넣도록 수정했다. 같은 본문·다른 상태를 연속 작성하는 회귀 테스트를 추가했다.
- 총괄 검증: 관련 집중 16/16, wheel·sdist 빌드 성공, 전체 622 OK(1 skipped). 별도 독립 재검토와 최종 검증 결과는 해당 검토 문서에 기록한다.
- 미실행/제한: 실제 개인 DB·자동 주문·실시간 공급자 재조회는 수행하지 않았다. 수치·차트 컨텍스트는 아직 고정 분석 모드에 소비되지 않으며 승인된 투자 정책과 13F 기간 외 검증도 없다.
