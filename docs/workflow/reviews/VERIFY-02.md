# VERIFY-02 — 독립 최종 검증

검증일: 2026-09-28 (Asia/Seoul). 검증 세션 작업 폴더: `C:/Users/lsn/Documents/Codex/2026-09-28/investment-stack-verify-01`.

**판정: 지정 SHA의 구현 범위 검증 PASS. R01–R17 전체 제품 요구사항 완료 또는 실사용 투자판단 승인으로 해석하면 안 된다.** 이번 세션이 직접 빌드·설치·실행한 결과이며 다른 세션의 통과 보고를 근거로 대체하지 않았다. 신규 runtime 결함은 실행 범위에서 발견하지 못했다.

## 버전·격리·안전

- 원본: `C:/Users/lsn/lsn-asset-mng-skills`.
- 대상 통합 SHA: `2a078da91ddfd761a1785ee482f3cd23eb1acaf7`.
- 마지막 runtime SHA: `4e55a560b4245ad5fb63cf4de8a2ce9813a2752a`.
- 시작 직후 `git status --short`, `git rev-parse HEAD`, 두 SHA의 `git show -s` 실행. HEAD 일치, status 출력 없음. 두 SHA 간 diff는 문서·검증 자료 7개 파일뿐이며 runtime 차이 없음.
- exact SHA archive와 `git clone --local --no-hardlinks --no-checkout` 후 detached checkout을 각각 만들었다. 최종 검증 Git 복제본은 `work/exact-clone`, HEAD는 끝까지 대상 SHA이고 status clean.
- archive 453개 추적 파일과 해당 Git blob을 CRLF/LF 정규화 후 대조했다. 원본/기존 테스트 편집 없음. 빌드와 로그는 본 작업 폴더에만 생성.
- 합성 임시 personal/run DB만 사용. 실제 개인 DB·자격증명·주문·외부 게시·원격 push·배포 미사용. 의존성은 로컬 pip HTTP cache의 wheel로만 설치했고 다운로드하지 않았다.
- 종료 확인 때 원본 HEAD는 `06871bc3e3783a43e794f447b4f74485a89e0d0f`로 전진해 있었다(status clean). 이는 총괄의 선행 VERIFY-01 인수 문서 변경이며 본 검증 대상이 아니다. 해당 커밋에 다른 세션의 VERIFY-01 문서가 있으므로 이 세션은 원본 문서를 덮어쓰지 않고 outputs에 별도 인계한다.

## 실제 실행 결과

| 검사 | 이번 실행 결과 | 근거 파일 (`VERIFY-02-evidence/`) |
|---|---|---|
| exact archive wheel + sdist 빌드 | PASS | `build.log` |
| exact Git clone wheel + sdist 재빌드 | PASS | `clone-build.log` |
| clone 소스 전체 unittest | 600 실행, OK, 설치 전용 1 skip (84.828초) | `clone-source-unittest.log` |
| clean wheel 설치 환경 전체 unittest | 600 실행, OK, 0 skip (84.923초) | `clone-wheel-unittest.log` |
| 보존 독립 probes | 20/20 PASS: 5+3+5+3+3+1 | `first_pass_probes.log`, `interim_probes.log`, `b1f4514_probes.log`, `final_probes.log`, `dcd262a_probes.log`, `briefing_persistence_probe.log` |
| refresh manifest 경계 | 10/10 subcase PASS (unittest method 1개) | `refresh_binding_checks.log` |
| 브리핑 roundtrip/refresh | 2/2 PASS | `rc12_roundtrip_checks.log` |
| clean 설치 packaging/sync | 11/11 PASS | `installed-packaging.log` |
| `sync_agent_skills.py --check` | exit 0 | `extra-checks.log` |
| `investment_stack check --project-root . --json` | 11 invariant PASS | `architecture-check.json` |
| wheel 실제 설치 payload | runtime 116개 + data 37개 byte equality | `artifact-audit.json` |
| archive와 clone 빌드 wheel | 158 member 내용 전부 동일 | `artifact-audit.json` |
| sdist unpack 후 wheel 재빌드 | PASS, 직접 빌드와 158 member 내용 동일 | `sdist-rebuild.log`, `extra-checks.log` |
| default CLI 미설정 실행 | UNSUPPORTED, mutation_receipt null | `cli-unconfigured.json` |

600은 unittest discovery가 보고한 실행 수이며 고유 사업 시나리오 개수라는 뜻은 아니다. source skip은 `test_installed_skill_and_ui_discovery_files_are_exact`로, clean wheel 전체 실행과 별도 packaging 실행에서는 통과했다. 보존 probe 출력의 `baseline_sha` 상수는 과거 반례 설명 문자열이며 이번 실행 SHA가 아니다. 실제 실행 파일은 대상 SHA archive에서 추출한 원본 그대로다.

환경: Windows, Python 3.14.6 AMD64. Build interpreter: `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`. Clean interpreter: 본 작업 폴더의 `work/clean-venv/Scripts/python.exe`. clean venv는 system site-packages를 사용하지 않았고 runtime import는 그 venv의 `Lib/site-packages/investment_stack/__init__.py`에서 확인했다. 설치 버전 investment-stack 0.1.0, tzdata 2026.4, truststore 0.10.4; `pip check` 통과, America/New_York·Asia/Seoul 로드 통과.

## 중점 경계의 관측 결과

1. **고정 cutoff**: `tests/integration/test_r01_weekend_price_e2e.py`를 전체 source/wheel 실행에서 각각 통과. 2026-09-27 NASDAQ 시나리오는 9/25 종가 341.07(합성 payload), KRX 추석/일요일 시나리오는 9/23 종가 286500(합성 payload)을 LAST_VALID_CLOSE로 검증해 Phase4 저장과 Phase5 valuation.current_price까지 전달했다. 브리핑 근거에 거래일·공개시각·실시간 아님 표시를 검사했다. KRX 9/23 16:00 공개 전과 9/28 10:00 재개장 후에는 해당 종가를 거부했다. 이 가격은 본 세션이 수집한 실제 9/28 가격이 아니다.
2. **configured 7모드**: 실제 composition/handlers를 합성 의존성으로 실행. ASSET_UPDATE의 명시적으로 확정한 합성 입금만 POSTED 영수증/상태 증가. 나머지 분석·시나리오·thesis·refresh는 mutation receipt 없음, 원장 state_version 불변, 저장 report ref 조회 가능. RC03 probe는 게시 이후 projection/log 실패에도 게시 영수증이 유실되지 않음을 재확인했다.
3. **refresh PARTIAL**: replay의 저장 manifest가 PARTIAL이면 외부 snapshot이 AVAILABLE이라고 주장해도 PARTIAL 유지. `approved_materiality_selector`, `selected_assets_for_deep_research` 누락이 최종 결과·보고서까지 유지됐다. 유효 complete manifest만 COMPLETE. ref 부재, run/mode/target/assumptions/clock/section mismatch 및 외부 unavailable/missing을 COMPLETE로 승격하지 않았다.
4. **브리핑 저장·ref·history**: 본문 변경 시 report ref와 section ref 변경. 동일 본문 재렌더는 ref 재사용. DB 재개방 후 두 버전 본문과 typed WAIT 복원 및 SHA-256 content ref 일치. 실제 equity refresh에서 final_briefing CHANGED와 전후 fingerprint 확인. 브리핑 numeric_bindings는 빈 배열이며 이는 실행 가능한 가격/수량 권고가 완성됐다는 뜻이 아니다.

## R01–R17 확인 범위와 미완 제한

아래 PASS는 실행한 코드 경계에 대한 판정이다. 요구사항 자체가 완성됐다는 선언은 마지막 열과 함께 판단해야 한다.

| ID | 직접 실행한 근거/확인 내용 | 남은 제한·미실행 |
|---|---|---|
| R01 | calendar_last_valid_close, r01_price_binding/delayed_quote_gate, r06_last_valid_close_provider, weekend E2E: 미래·잘못된 통화/시장·달력 없는 가격 차단, 종가 Phase4→5 PASS | NASDAQ/KRX의 제한된 pinned 2026-09 달력. 범용 거래소/임의 날짜 live 보장 아님 |
| R02 | r02_financial_selection_consumption, 독립 RC04 및 EPS context 누락 probe: 기간/회계 비교와 선택 순서 PASS | 모든 해외 공시·회계 유형 live coverage 미검증 |
| R03 | contract_slots/calculations, r04_decimal_evidence, live_deep_research 단위/통화 사례: 모호 배율·비유한 값·통화 충돌 및 evidence 계보 PASS | 모든 외부 단위 표현 지원 주장 없음 |
| R04 | r04_sec_companyfacts/decimal_evidence: fixture fact 기간·단위·공개시점·정정 및 선택 PASS | 새 SEC live 응답 수집 미실행 |
| R05 | r05_fallback_eligibility/price_evidence, phase4_research_flow: 부적격 후보 후 fallback, 소진·미래가격 차단 PASS | 공급자 현재 가용성 미검증 |
| R06 | r06_r07_market_quotes_ohlcv, last_valid_close_provider, HTTP/TLS/UA fixture 및 source metadata gate PASS | 본 세션 live 페이지/API 접근 미실행. Investing/Naver/Yahoo 현재 접근성 판정 없음 |
| R07 | OHLCV parser·BarSet 단위 테스트: 관계/순서/중복/완성/adjustment gate PASS | 조정 receipt 진위 검증 없음. raw Sequence[Bar] 자체는 provenance 보증 없음 |
| R08 | r08_technical: SMA/EMA/RSI/MACD/ATR/변동성 등 deterministic 계산 PASS | chart evidence→완전한 행동 브리핑 통합 미완. 승인된 signal policy 미확정 |
| R09 | phase5_equity_valuation, live_deep_research, contract 계산: 명시 가정/범위/민감도/계보·누락 경계 PASS | 실제 종목 투자 유효성·미래 시장가격 예측 정확도 미검증 |
| R10 | decisions briefing 및 dcd262a probe: 5단계 한국어 WAIT, 누락 입력이 매수 확정 안 함 PASS | 승인된 매수정책, 안전마진/진입구간/분할매수 완성 미확인. 요구사항 미완 |
| R11 | portfolio scenario, decision/ledger 회귀: 비게시·원장 불변, 합성 budget 경계 PASS | 사용자 위험예산/실제 수량·금액 자동 sizing 및 완전한 추가매수/축소 통합 미완 |
| R12 | r12_sec_13f, period_continuity, pit_scoring: 정정/수량/분기/미래 기간/기관별 연속성 PASS | 최신 원문 live 수집과 전체 manager universe 검증 미실행 |
| R13 | r13_validation, pit_scoring 및 RC11: 미래정보 차단, 기간 연속성/일치도 gate PASS | 실제 과거·기간 외 성과 검증 미실행. 투자 가중치 확정 안 됨 |
| R14 | routing/intent/composition 및 configured 7모드 probe PASS; posting receipt와 비게시 구분 | host가 DB/provider/loaders/policy를 주입해야 함. 기본 CLI UNSUPPORTED 직접 확인 |
| R15 | clean wheel, sdist, 8 skills/8 mirrors/UI metadata, exact allowlist·37 data files PASS | venv 경로에서 Codex UI 자동 발견 미검증. Python 3.11–3.13/다른 OS 미실행. 경로 allowlist는 source text 비밀 스캔 아님 |
| R16 | 본 독립 세션 exact SHA build와 전체 600 source/wheel·20+10+2 probes PASS | live 수집→완전한 action briefing 전체 체인의 실환경 인증 아님 |
| R17 | Korean display, ordered WAIT briefing, persistence/ref/history/refresh, 수치 formatting 회귀 PASS | chart/13F 및 actionable numeric binding을 포함한 완성 브리핑 미완. 사용자 가독성 실험 미실행 |

## 실패와 해결 및 발견

- archive 전체 실행은 600개 중 **12 failure events(한 Git ignore 테스트의 subtest 포함)**, 설치 전용 1 skip이었다. `.git` 없이 실행해 상위 저장소 탐색/ownership 문제로 Git exit 128이 나온 환경 결함이다. Git 메타데이터를 가진 exact clone에서 source/wheel 전체 실행으로 해결했다. 원본 소스 수정 없이 재현 조건을 제거했으므로 runtime 결함으로 분류하지 않는다. 실패 로그도 보존한다.
- 첫 clone은 source `.git` 소유권 검사로 거부됐다. 명령 단위 `-c safe.directory=<source>` 및 `-c safe.directory=<source>/.git`만 지정해 읽기 clone했다. 전역 설정/권한 변경 없음.
- pip cache에서 tzdata wheel을 복구할 때 첫 filename tag를 py2로만 쓴 harness 오류가 있어 offline 설치가 실패했다. WHEEL의 복수 Python tag에 맞는 `py2.py3-none-any` 이름으로 정정 후 정상 설치했다. 패키지 payload 변경 없음.
- 원본 `.venv`에서 `pip show` 전체 metadata 출력은 cp949 인코딩 오류가 발생해 이후 `PYTHONIOENCODING=utf-8` 사용. 버전/의존성은 clean 설치 결과로 확인.
- Git archive/checkout CRLF와 blob LF 차이는 파일 변조로 취급하지 않고 Git blob 대조에만 줄바꿈 정규화를 적용했다. wheel/install/sdist member 대조는 **바이트 그대로** 비교했다.
- default CLI 첫 smoke에서 빈 stdin이 JSONDecodeError로 거부돼 명시적 `{}`를 입력해 UNSUPPORTED 경계를 확인했다.
- 문서 정합성 참고: 대상 SHA의 IMPLEMENTATION_STATUS 최신 단락은 WAIT 연결 완료를 설명하나 아래 `Current Integrated Checkpoint (a1a41b0)`에는 아직 연결 작업 중이라는 과거 설명이 있다. 최신/과거 경계를 읽어야 하며 후속 문서 정리 권장. runtime blocker 아님.
- 새 제품 결함/반례는 발견하지 못했으므로 결함 재현 파일 회송 대상 없음. 위 환경 오류와 미완 요구사항은 통과 수치에 숨기지 않았다.

## 재현 명령과 산출물

작업 기준은 위 세션 폴더다. source clone에서는 `$env:PYTHONPATH=(Resolve-Path runtime).Path`, clean wheel에서는 PYTHONPATH를 제거한다. 두 경우 모두 `PYTHONIOENCODING=utf-8`, `PYTHONDONTWRITEBYTECODE=1`을 사용했다.

```powershell
# work/exact-clone에서, 이미 선언 의존성이 있는 build interpreter 사용
& C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m build --wheel --sdist --no-isolation
& C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest discover -s tests -v
# clean target interpreter, source PYTHONPATH 없이 실행
& ../clean-venv/Scripts/python.exe -m unittest discover -s tests -v
& ../clean-venv/Scripts/python.exe -m unittest tests.test_packaging tests.test_r15_skill_sync -v
& ../clean-venv/Scripts/python.exe scripts/sync_agent_skills.py --check
& ../clean-venv/Scripts/python.exe -m investment_stack check --project-root . --json
```

보존 probes 실행 목록은 evidence의 `run_preserved.py` 및 `preserved-results.json`에 있다. 소스/테스트를 수정하지 않고 각 파일을 별도 subprocess로 실행했다. `artifact_audit.py`는 자체 추가 검증 harness이며 runtime 변경이 아니다. 추가 실행 로그 및 evidence 파일 checksum은 `VERIFY-02-evidence/SHA256SUMS.json` 참조.

직접 clone 빌드 artifact SHA-256:

- wheel `investment_stack-0.1.0-py3-none-any.whl`: `9054c10d29035211edc9cee8577129812144dfc4df0cef7280517567f983df12`
- sdist `investment_stack-0.1.0.tar.gz`: `73057a2cc4bb0504636bf3a1288c561f2c230da2d80d99b8b71a025ee7979bfd`

전체 재빌드 시 ZIP/tar의 timestamp 차이로 archive hash 자체는 달라질 수 있다. 이 세션은 member 내용 equality를 별도로 검증했다. 산출물은 본 작업 폴더 `work/exact-clone/dist`에 보존했다. 총괄은 이 문서와 evidence를 검토해 공유 docs로 인수할 수 있으며 본 세션은 원본에 commit하지 않았다.

총괄 후속 지시: 먼저 요청된 worktree 검증 세션이 뒤늦게 완료되어 VERIFY-01로 인수됨. 본 projectless 세션은 최초 배정명 VERIFY-01에서 최종 산출물명 VERIFY-02로 구분하며, 실행 결과는 모두 본 세션이 직접 얻은 것이다.
