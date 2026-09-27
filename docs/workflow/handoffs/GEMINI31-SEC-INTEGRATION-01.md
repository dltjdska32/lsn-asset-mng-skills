# GEMINI31-SEC-INTEGRATION-01 — SEC parser 수직 슬라이스

2026-09-27. Gemini A `962930d` (`gemini-3.1-pro-high`, SEC-01/02/03 file tools only)에서 `providers/adapters.py`, R04 신규 테스트 5개, 3개 인계를 root `5d094a5`에 cherry-pick. SEC-01 신규+기존 10개 중 2 FAIL. SEC-02 신규 5개 중 1 ERROR; 셋째 수정 후 신규 5/5 PASS. 기존 `test_phase4_providers`의 빈 `Revenue` tag AVAILABLE 기대는 R04 '적격 fact 0개는 조회 성공 아님'과 모순이므로 총괄이 UNAVAILABLE/0 observations로 변경. 변경한 root tree의 전체 unittest **475 OK, skip1**. 개인 DB·인증정보 사용 안 함. source `962930d`, 통합 parser `5d094a5`, B 문서 포함 root HEAD `7c8f8f4` (기존 테스트 갱신 및 이 인계는 작성 시 미커밋).

이 코드는 지원된 us-gaap/dei fact row의 개별 관측·원본 metadata·filed cutoff·제한된 USD/주식 단위·form 검증에 한정된다. 다중 fact를 기간/회계 기준에 맞춰 `SelectedInputSet`/계산에 결속하는 R02–04 완료는 아니다. provider PARTIAL/coverage 뒤 재시도 R05도 A 후속이며 아직 통합되지 않았다. B 문서 작업의 DOCS-01은 RunCommand denied/빈 응답으로 미인수, 복원 뒤 DOCS-02는 SUCCESS/denied0 및 B `fccbe84`로 인수했다.
