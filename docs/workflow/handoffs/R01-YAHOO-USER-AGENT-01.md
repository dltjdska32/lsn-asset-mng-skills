# R01-YAHOO-USER-AGENT-01 인계

- 요구사항: `REQ-2026-09-23-v1` R01/R06; 설계: `DESIGN-2026-09-23-v0.1` 초안.
- 기준: 총괄 지정 root `c6e63d9a664d7f9f356685fd15221752328c2827`.
- Branch/worktree: `codex/luna-price-rc03-rc04` / `C:/Users/lsn/.codex/worktrees/luna-price-rc03-rc04/lsn-asset-mng-skills`.
- 담당 파일: `runtime/investment_stack/providers/market_quotes.py`, 전용 `tests/unit/test_r01_yahoo_user_agent.py`.

## 변경 및 검증

- Yahoo Finance Chart HTTP 후보에만 `User-Agent: Mozilla/5.0`와 `Accept: application/json` 헤더를 적용했다. 다른 quote 후보는 기존 헤더 동작을 유지한다. TLS 검증은 기존 `urllib_transport` 경계에서 유지한다.
- 기본 executor에 주입한 HTTP transport를 통해 헤더 전파와 Yahoo 후보 선택을 확인하는 synthetic unittest 추가.
- 실 Yahoo 공개 endpoint에서 지정 Windows TLS transport로 기본 executor 실행: 2026-09-27 Sunday cutoff에서 `NASDAQ:AAPL`이 `AVAILABLE`, Yahoo 선택, session `2026-09-25`, 값 `341.07 USD`. 사용자 관찰과 일치하게 Yahoo 응답은 정상 수신·파싱·calendar gate 통과했다. 개인 데이터는 쓰지 않음.
- 실행: `tests.unit.test_rc03_yahoo_user_agent` 통과. 상세 하위/full regression은 RC03/RC04 통합 인계에 기록.

## 남은 점

- Yahoo 공개 API는 rate limit/응답 스키마가 바뀔 수 있고, 이 한 번의 live 확인은 지속 가용성을 보증하지 않는다. 지연/거래소 적격성은 별도 gate에서 계속 검증한다.
