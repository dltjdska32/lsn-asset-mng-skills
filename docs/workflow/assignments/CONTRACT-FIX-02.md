# CONTRACT-FIX-02 — 실제 실행 실패 수정

Gemini A, 기준73d376e, REQ-v1/실행v0.2. 소유권은 CONTRACT-FIX-01과 같음. shell/git/pip/web 도구 금지. 총괄이 방금 완료본을 직접 실행한 로그가 자기 worktree `workspace/runs/CONTRACT-FIX-final.tests.log`에 있다. **전체 로그를 읽고 현재 실제 정의된 API와 테스트를 맞춰 수정**하라. 기록: 37 tests, failures2/errors10, import 실패 때문에 일부 suite 자체가 실행되지 않음. 추측한 이름/필드를 더 만들지 말고 현재 소스를 읽어 일관된 작은 수정으로 해결하라. 계약을 다시 전체 재설계하지 않는다.

실제 오류:
- evidence.manager가 존재하지 않는 codec.MAX_PAYLOAD_BYTES를 import하여 전체 runtime을 깨뜨림. size상수는 실제 정의 위치와 일치시킬 것.
- MarketQuote encode_contract→decode_contract의 nested PublicAvailability가 plain payload인데 decoder는 envelope를 기대하여 roundtrip 실패. FinancialFact/Bar/BarSet/Holding13F/Filing13F/HoldingSet/FinancialSet/RunContext/CalculationRecord 전체 nested typed encode/decode를 한 가지 규칙으로 맞추고 strictness·unknown-field 거부 유지. raw canonical hash 표현과 wire typed representation 혼동 금지.
- test_contract_adapters: ReportingFrequency.QUARTERLY 없고 QUARTER가 실제 정의, ProviderObservation에 observation_id 없음. canonical Decimal '95000.50'→'95000.5'는 설계상 정상이며 테스트는 정확한 canonical 기대값으로 확인.
- test_contract_context: exact는 locator 필수인데 안 줌; 제거된 date_interval를 호출; from_source_date 실제 signature와 tz keyword 불일치. valid fixtures는 source locator/timezone을 제공, invalid input은 명시한 domain rejection assert. public-time 보수 검증을 없애지 않는다.
- test_contract_domain_models는 이동 전 contracts.adapters에서 bar_to_observation 등을 import해 실행 불가. providers.contract_adapters로 실제 API 맞추고 다른 constructor 변경까지 전체 확인.
- exception message substring에만 의존한 codec 테스트가 새 메시지와 불일치. 도메인 예외와 실제 unknown field reject를 검증하면 되며 문구만의 차이는 맞춰도 좋다.

추가 static 확인: fetch_active_contract_snapshot(purpose)와 storage active key가 purpose만이면 같은 run의 두 종목 비교가 서로 덮어쓴다. SelectionSnapshot/SelectedInputSet에 canonical request hash 또는 instrument+purpose+slot-coherence key를 포함하여 저장/조회하고 backward API가 ambiguous한 경우 거부하라. 동일 run/같은 purpose/서로 다른 instrument에 대한 두 snapshot이 각각 조회되는 테스트와 같은 request revision 교체 테스트를 추가. primary key와 semantic hash 경계도 유지.

위 실행 오류를 수정하고 수정 중 새 이름을 발명하여 다른 파일과 어긋나지 않도록 dependent imports/constructors를 파일 도구로 확인한다. 기존 반례·검증을 통과시키기 위해 느슨한 decoder/어떤 값이든 허용하는 default를 도입하지 않는다. 총괄은 종료 후 같은 테스트와 전체 회귀를 실행한다. 간결한 handoffs/CONTRACT-FIX-02.md에 변경 파일·실제 API·미실행 테스트를 적고 종료. 큰 장문 보고서 대신 수정과 검증 요청에 집중하라. 실행하지 않은 테스트 통과를 주장하지 않는다.
