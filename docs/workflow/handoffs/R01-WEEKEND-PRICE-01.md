# R01-WEEKEND-PRICE-01 인계

- 요구사항: `REQ-2026-09-23-v1`, R01; 설계 참조: `DESIGN-2026-09-23-v0.1` (초안).
- 작업 브랜치: `codex/luna-a-weekend-price-01`; 기준 커밋: `02a5710e0c5b43be661a14306c0ee0bc2a68889f`.
- 구현 소유: Codex A. 별도 변경 커밋은 아직 만들지 않았다.

## 구현

- 기본 executor에 NASDAQ/KRX pinned schedule을 쓰는 `MarketQuoteProviderAdapter`를 등록했다. HTTP는 기존 `urllib_transport`와 TLS 검증 경계를 유지하며, market quote transport tuple을 얇게 감싼다.
- provider fallback, Phase 4 evidence selection, Phase 5 price binding이 같은 calendar-aware freshness 함수를 사용한다. 주식은 알려진 listing/calendar·통화·거래소 ID 확인 뒤 `FRESH`/`LAST_VALID_CLOSE`만 계산 입력으로 허용한다. Crypto는 24/7 age freshness 경로를 유지한다.
- Phase 4는 LAST_VALID_CLOSE의 날짜·시각·calendar/publication lineage를 `run.db` freshness/evidence에 저장한다. stale 가격 관측은 원 값·시각·freshness 상태를 run.db에 보존하지만 선택 상태로 표시하지 않으며 Phase 5 가격 입력에서도 거부한다.
- 검색 웹페이지의 metadata는 페이지가 자기주장할 수 있어 현재가 근거로 승인하지 않는다. 검색 웹 현재가 경로는 `UNAVAILABLE`로 닫혀 있고 검증된 market quote provider를 사용해야 한다.
- LAST_VALID_CLOSE 가치평가 finding은 `가격 입력 기준: <일자> 마지막 유효 거래일 종가`, 종가/공개시각, 달력 ID와 `실시간 시세가 아닙니다`를 한국어 보고서 섹션에 표시한다. 숫자 가격은 자연어로 복제하지 않고 계산 결과의 typed metric에 둔다.

## B 소유권 이전

- 2026-09-27 총괄의 명시 지시에 따라 B의 `providers/market_quotes.py` 파일 소유권을 이 R01 필수 adapter normalization 변경에 한해 순차 이전했다. 이전 기준은 B source `d1052d1` 통합 완료 이후이며, 같은 파일의 병렬 편집은 없음을 총괄이 확인했다.
- 변경: 계약 adapter의 `MARKET_QUOTE`/`price`를 Phase 4 `market`/`current_price`로 정규화하여 run.db market evidence 및 Phase 5 lineage에 연결했다. 결과 metadata에서 JSON 직렬화 불가능한 `contract_quote` 객체만 제거했다. 원 quote provenance는 observation의 `quote_id`, `evidence_id`, `quote_kind`, `exchange`, `public_availability`, `claimed_market_time`, `market_session_date`와 Phase 4 freshness 상세의 `calendar_id`, `public_available_time`에 계속 남는다.
- 소유권 이전 범위는 이 파일 한 곳뿐이며 B 소유 freshness/calendar 파일은 수정하지 않았다.

## 검증

- `tests/integration/test_r01_weekend_price_e2e.py`: NASDAQ/Yahoo와 KRX/Naver를 각각 실제 Phase 4 → `run.db` → `LiveDeepResearchRuntime`/Phase 5 입력 → Phase 6 valuation section까지 합성 fixture로 확인. Sunday close의 Decimal price binding, `calendar_id`, session date, public availability와 한국어 비실시간 라벨을 assertion했다. KRX publication 전과 2026-09-28 재개장 이후는 선택되지 않는다. 임의 웹 metadata의 quote 주장은 거부한다.
- 집중 회귀: `test_r01_price_binding`, `test_r06_last_valid_close_provider`, `test_r06_r07_market_quotes_ohlcv`, `test_phase4_research_flow`, `test_live_deep_research`, `test_phase4_freshness_web`, `test_r05_price_evidence`, `test_r14_equity_mode_bundles`, 신규 R01 E2E: **68/68 PASS**.
- 전체 `unittest discover -s tests -q`: **547 tests, OK, skipped=1**. packaging 검증을 위해 local `python -m build`로 wheel/sdist 생성 뒤 elevated read 권한으로 전체 suite 실행했다. sandbox ACL 때문에 build artifact를 생성·읽는 작업에는 권한 상승이 필요했다. 가격 웹 경로를 fail-closed로 바꾼 정책에 맞춰 acceptance/unit/live deep/R14 fixture 기대값을 수정했다.
- 공개 HTTP/API 가격 조회는 하지 않았다. Yahoo/Naver fixture는 결정론적 synthetic 입력이며 실제 provider 응답을 새로 검증한 것으로 표현하지 않는다.

## 남은 일과 경계

- 빌드 산출물은 로컬 `dist/`에만 두었으며 커밋 대상이 아니다.
- `NYSE` pinned calendar는 현재 registry에 없으므로 NYSE quote는 fail-closed다. pinned calendar coverage 밖 날짜도 승인되지 않는다.
- personal DB 변경 및 주문 동작은 없었다. 원격 push/deploy도 수행하지 않았다.
