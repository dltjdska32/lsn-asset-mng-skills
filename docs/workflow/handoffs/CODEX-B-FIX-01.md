# CODEX-B-FIX-01 — IMPL-B-FIX-03 인수 사본

총괄이 `codex/luna-b` 최종 HEAD `9252038100cf748e77f35996fde1cd1ae4d53cfd`에서 원본 `docs/workflow/handoffs/IMPL-B-FIX-03.md`를 복사했다. 같은 버전에서 담당 unittest 19/19와 공개 응답 사본 probe 6/6을 총괄이 직접 재실행해 확인했다. 아직 root 통합과 전체 독립 검토는 하지 않았다.

- 담당: Codex GPT-6 Luna B
- 요구사항: REQ-v1 R06–08, 설계 v0.1 / D18
- 작업 branch: `codex/luna-b`
- 시작 HEAD: `d2db94f5d46b6e2ea04d28be0384d8b0400a923b`
- 구현 및 검증 HEAD: `b23ec247e9ffbcf9b7d6bc49b8c5db3a2fe96762`
- 기준 코드 변경 commit: `b23ec247e9ffbcf9b7d6bc49b8c5db3a2fe96762` (`fix: validate crypto quote source pairs`)

## 변경

- `providers/market_quotes.py`: Coinbase/Kraken BTC/USD 고정 source에 BTC/EUR 등 다른 쌍을 보내지 않고 명시적으로 UNAVAILABLE 처리. Kraken Trades는 `XXBTZUSD`, `XBTUSD`, `BTCUSD` 결과 키만 수용. Kraken Ticker도 허용 pair alias만 선택하고 임의 첫 result fallback을 제거. `CURRENT_PRICE` capability가 없는 후보는 실행하지 않음.
- `web_research/quote_sources.py`: 임의 문자열 내 BTC/XBT 포함으로 시장을 분류하지 않도록 `CRYPTO:` base symbol을 확인. BTC/USD 외 지원되지 않는 quote currency는 helper에서 거부. `execute_quote_fallback_sequence`의 시세 조회 시각은 analysis cutoff 대신 주입 가능한 실제 clock을 사용.
- B 담당 테스트 파일에 종목쌍 거부, Kraken 응답쌍 거부, caller eligibility 탈락 뒤 Kraken fallback, helper 조회시각, SEC fundamentals의 시세 후보 제외 회귀를 추가.

## 실행한 검증

- `tests.unit.test_r06_r07_market_quotes_ohlcv`: 19 tests, PASS (bundled Python runtime, `PYTHONPATH=runtime`).
- `scripts/workflow/market-fallback-checkpoint-probes.py --repo <codex-luna-b> --source-inputs <gemini-b>/workspace/runs/source-inputs`: 6/6 PASS. BTC/USD primary 1-call, HTTP/parse/future-time 이후 Kraken fallback 2-call, 모두 실패 시 UNAVAILABLE와 attempts, BTC/EUR 무호출 거부를 확인. 공개 응답 사본을 그대로 replay한 오프라인 probe이며 live E2E가 아님.
- `py_compile` 대상 세 파일 성공.
- `git diff --check` 성공.

## 미실행 및 남은 범위

- 전체 repository test suite 및 외부 API live E2E는 실행하지 않음. 자동 주문·개인 DB·인증정보에는 접근하지 않음.
- `execute_quote_fallback_sequence` helper는 기존 시그니처 호환을 위해 eligibility evaluator를 추가하지 않았음. 명시 eligibility fallback은 운영 provider API `MarketQuoteProvider.fetch_current`로 검증.
- Probe는 총괄 소유 경로의 갱신본을 사용했고 해당 파일은 이 worktree에서 수정하지 않음.

구현 commit은 `b23ec247e9ffbcf9b7d6bc49b8c5db3a2fe96762`; 이 인계 문서의 commit은 바로 뒤에 생성됩니다. 원격 push/deploy 없음.
