# VERIFY-01 — 독립 최종 검증

## 판정과 기준

**명시된 구현 범위의 최종 검증 통과.** R01–R17 전체 제품 기능 완료, 매매 정책 승인, 실계좌 운영 또는 배포 승인이 아니다. REVIEW-CODE-01의 통과 문구를 검증 근거로 대체하지 않고 아래 명령·probe·공개 조회를 이 별도 세션에서 직접 실행했다. 새 P1/P2 런타임 결함은 발견하지 않았다.

- 대상 HEAD: `2a078da91ddfd761a1785ee482f3cd23eb1acaf7`.
- 마지막 runtime 변경: `4e55a560b4245ad5fb63cf4de8a2ce9813a2752a`. 두 SHA 사이 runtime diff 없음. 후속 문서와 RC12 검증 스크립트/출력만 추가됨.
- 격리 worktree: `C:/Users/lsn/.codex/worktrees/bfbc/lsn-asset-mng-skills`.
- 기본 HEAD `3d4a95b`에서 지정 SHA로 직접 detached checkout하고 시작·종료 HEAD를 확인했다. 첫 checkout의 공용 Git index 쓰기는 sandbox에 차단되어 동일 checkout을 승인된 escalation으로 완료했다.
- 검증일: **2026-09-28 KST**. 공개 조회 기록의 UTC는 `2026-09-27T15:49:22–23Z`이며 한국시간 9/28 00:49이다.
- 읽은 기준: AGENTS, README, ARCHITECTURE, IMPLEMENTATION_STATUS, requirements/design/tasks, REVIEW-CODE-01과 인계, 8개 원본 스킬, packaging allowlist 및 관련 runtime/tests/probes.
- 구현·기존 테스트·스킬 변경 없음. 임시 합성 personal/run DB만 사용. 실제 개인 DB·인증정보·주문·원격 push·배포 없음. 공개 시세 호출에는 `EnvironmentCredentials({})`를 명시했다.

## 직접 실행한 검증

빌드 인터프리터는 `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`, Windows Python **3.14.6**, build **1.6.1**, setuptools **84.0.0**이다. 소스 검사는 이 worktree의 절대 runtime 경로를 PYTHONPATH로 사용했다. 빌드 환경에는 설치/변경하지 않았다.

| 검사 | 직접 결과 |
|---|---|
| `python -m build --wheel --sdist --no-isolation` | 성공, 두 artifact 신규 생성 |
| `python -m unittest discover -s tests -v` | **600 tests OK, skipped=1**, 86.619초 |
| 기본 discover에서 제외되는 `tests/providers`, `tests/calculations` 별도 discover | **8 + 4 tests OK**; 기본 600에 포함된다고 주장하지 않음 |
| first-pass / interim / b1 / a1 final / dcd / RC12 원 반례 | **5 + 3 + 5 + 3 + 3 + 1 = 20/20 PASS** |
| RC10-R2 stored manifest 검사 | **10/10 subtests PASS** (unittest 1개, 9.549초) |
| RC12 history/reopen/hash/실제 refresh | **2/2 PASS**, 7.549초 |
| clean wheel R15 packaging/skill tests | **11/11 OK, skip 없음**, 0.996초 |
| clean installed wheel에서 전체 unittest 재실행 | **600 tests OK, skip 없음**, 86.708초; PYTHONPATH 제거 |
| clean wheel `pip check`, import 위치, 두 IANA timezone | 성공; site-packages import 직접 assertion |
| `sync_agent_skills.py --check` | 성공, 8개 원본/미러 및 UI metadata 동일 |
| clean installed CLI `check --project-root .` | 11 invariant PASS |
| 소스/신규 wheel/실제 설치 runtime 바이트 대조 | **116 Python 파일 일치**; 원본/설치 skill payload **32파일 일치** |
| 현 sdist를 풀어 자체 wheel/sdist 재빌드 및 포함된 테스트 실행 | **11 tests OK, skipped=1**, 0.839초; RC08 버전·ARCHITECTURE 경계 포함 |
| VERIFY 신규 실제 합성 ledger fault/retry | PASS, 실제 commit 뒤 logging 실패에도 receipt 유지·재시도 중복 게시 없음 |
| VERIFY 신규 default factory 기반 9/27 고정 시세 replay | Yahoo/Naver 두 경로 PASS, Phase4 저장→Phase5 가격 소비→비실시간 종가 고지 |
| VERIFY 신규 공개 HTTP→동일 고정 cutoff 경로 | 두 경로 PASS, 아래 live 범위 참조 |

전체 소스 suite의 skip은 설치된 prefix에 skill payload가 없어서 생긴 installed layout 검사다. clean wheel R15에서 해당 검사를 실제 실행했다. sdist는 배포 allowlist상 R15 테스트 2파일만 포함하며 전체 600개 suite를 포함하지 않는다. 과거 실패 RC08의 unpacked-sdist 자체 버전 검사를 현재 재빌드한 sdist에서 재실행했으며, 과거 SHA의 sdist를 다시 테스트한 결과로 표시하지 않는다.

clean target은 `workspace/verify-01/clean-wheel`의 system-site-packages 없는 새 venv다. 인터넷 패키지 다운로드 없이 로컬 **tzdata 2026.4 / truststore 0.10.4** 패키지와 dist-info를 복사한 뒤 `--no-index --no-deps`로 새 wheel을 설치했다. PYTHONPATH를 제거하고 설치 인터프리터를 명시했다. 저장소 root는 테스트/동기화 도구 import에 사용했지만 runtime 소스 경로는 넣지 않았다. 다른 Python 버전/OS와 임의 venv의 Codex UI 자동 발견은 검증하지 않았다.

빌드 artifact SHA-256:

- wheel: `8358529091b0165d8ce8372ef2764d9f04b01f962e075a5bebf7451041faed7f`
- sdist: `a984ba84b2f2e964ac9ff766802c5e25d2b57f712b7226da7eec73f80da33b98`

## 일곱 모드·게시·refresh·브리핑

보존된 `review_code_01_final_probes.py`를 현재 HEAD에서 직접 실행했다. ledger/equity/portfolio/thesis의 실제 번들을 동일 run.db에 조립하고 합성 research, typed state와 고정 외부 refresh runner를 주입한다. 일곱 고정 모드 모두 결과물까지 수행한다. ASSET_UPDATE의 확정 합성 입금만 POSTED/state 증가이고 다른 여섯 모드에는 receipt가 없으며 ledger version이 불변이다. 보고서 참조는 저장 manifest로 조회된다. 이 결과는 기본 CLI가 해당 서비스를 자동 구성한다는 뜻이 아니다.

기존 RC03의 projection failure + error logging failure 반례 외에 VERIFY 신규 probe는 **실제 PersonalLedgerService**로 1,234 USD 합성 입금을 commit한 직후 DECIDE_POSTING 상태 기록을 실패시킨다. 결과는 FAILED이나 POSTED/transaction IDs/state_version=1을 유지한다. 같은 idempotency key 재시도는 같은 IDs의 ALREADY_POSTED, state_version=1이다. 임시 DB는 context 종료 시 정리된다.

RC10-R2: 정상 complete manifest는 COMPLETE. 없는 ref와 run/mode/target/assumptions/clock/section 불일치는 PARTIAL. 외부 UNAVAILABLE은 PARTIAL이며 외부 누락 입력도 보존된다. 기존 PARTIAL replay의 `approved_materiality_selector`, `selected_assets_for_deep_research` 누락이 저장 manifest·ModeResult·보고서에서 유지되는 내부/외부 두 경로도 직접 통과했다.

RC12: 같은 run에서 서로 다른 WAIT 브리핑은 서로 다른 ref, 같은 내용 재렌더는 원래 ref를 반환한다. 정확히 두 버전이 저장되고 새로운 RunDatabaseManager로 다시 열어 과거/현재 manifest fingerprint에서 rendered_markdown·typed WAIT·numeric_bindings를 복원했다. JSON SHA-256를 재계산하여 content_reference와 일치함을 검증했다. 실제 configured equity refresh는 final_briefing CHANGED와 이전/현재 fingerprint를 반환했다. 이는 해당 브리핑의 이력 보존 검사이며 모든 일반 분석 section의 임의 버전 이력을 보증하는 검사는 아니다.

## 2026-09-27 고정 cutoff와 공개 조회

VERIFY 신규 probe의 cutoff는 **`2026-09-27T12:00:00+00:00`**이다. 라이브 조회 시각을 cutoff로 바꾸지 않았다. factory가 만든 기본 adapters/달력·기존 TLS 검증 HTTP transport를 사용했다. 시장 URL만 실제 호출하고 금융 데이터·그 외 transport는 명시적으로 빈 응답을 주었다. Web Research도 빈 합성 응답이다. Phase5는 wrapper로 전달 가격을 관찰했으며 실제 계산 함수는 그대로 호출했다.

| 원천 | 실제 선택 | 세션 / 공개가능시각 해석 | Phase5 / 상태 |
|---|---|---|---|
| Yahoo chart AAPL | USD **341.07**, LAST_VALID_CLOSE | 2026-09-25 / `2026-09-25T20:00:01+00:00` | current_price=341.07 / valuation PARTIAL |
| Naver basic 005930 | KRW **286500**, LAST_VALID_CLOSE | 2026-09-23 / `2026-09-23T07:30:00+00:00` | current_price=286500 / valuation PARTIAL |

두 경로에서 Phase4 market observation 저장 및 한국어 날짜·“실시간 시세가 아닙니다” 고지를 assertion했다. Yahoo 공개가능시각은 regularMarketTime의 parser 해석, Naver는 closePriceSendTime 기반 파생값이다. 독립적인 출판시각 field를 검증했다는 뜻이 아니다. KRX 추석/주말·NASDAQ 주말 처리는 registry의 **KRX 9/22–28, NASDAQ 9/24–28**에 한정된다. publication 이전, 재개장 이후 이전 종가, 미등록 거래소·통화·calendar 범위 밖 거부는 기존 suite에서 직접 통과했다.

공식 달력 원문을 새로 조사하거나 연속 거래일 전체의 정확성을 인증하지 않았다. 실제 조회 성공은 이 두 요청의 접근성과 고정 과거 cutoff의 종가 처리 증거다. 9/28 장중 실시간 가격, 일반 휴장일 서비스, 완전한 live 재무/가치평가, 모든 vendor 접근 검증으로 확대하지 않는다. Investing.com/SEC archives/OpenDART credentialed 호출은 이번 VERIFY에서 하지 않았다.

## R01–R17 구현 범위와 남은 기능

| ID | 이번 확인 | 명시 제한 / 완료로 간주하지 않는 부분 |
|---|---|---|
| R01 | 가격 binding·delay·미래/stale 거부, 두 원천의 LAST_VALID_CLOSE→4→5 | 두 pinned calendar 이외 일반 일정 및 모든 거래소 없음 |
| R02 | 선택 지표별 기간/회계 문맥, RC04 원·추가 반례 | 모든 공시/회계 조정과 전 시장 live coverage 인증 아님 |
| R03 | Decimal/배율/차원/FX 회귀, RC01 동등 경제상태 위험 | 실제 개인 FX/계좌 값 미사용 |
| R04 | SEC nested facts·공개시점·tag·Decimal evidence 회귀 | 새 SEC live 수집 및 전체 tag 감사 미실행 |
| R05 | stale/partial/잘못된 응답 이후 fallback·선택 회귀 | 모든 vendor 가용성 보장 아님 |
| R06 | Yahoo/Naver 공개 API 실제 원문 응답·종가 적격성 | Investing 등 다른 시장/원천 live 미검증 |
| R07 | OHLCV identity·순서·OHLC·미완성/조정 경계 | Naver adjustment receipt 진위 검증·일반 corporate actions 미완 |
| R08 | 지표 계산·최소 표본·미래 봉/gate 회귀와 추가4 | 차트→최종 action briefing 자동 결속 및 승인 signal registry 미완; raw Sequence[Bar] provenance는 호출자 책임 |
| R09 | 모델/가정/선택 입력·계보 회귀, 종가 전달 | 입력 부족 valuation은 PARTIAL; 모든 모델 live 성공 아님 |
| R10 | 5항목 WAIT·미검증 자료의 매수 차단 | 승인 매수 정책/차트·13F 결속/안전마진 진입 정책 미완 |
| R11 | 예산/FX/개인 위험·비게시 회귀 | 자동 추가매수/축소 수량·규모 승인/실개인 상태 검증 없음 |
| R12 | 13F 공개시점·정정·기간 역순/gap/중복 거부 | 전체 SEC archives live 수집·현재 실보유 확정 아님 |
| R13 | 기관별 기간 chain·기관 간 합의, UNVALIDATED/DISABLED | 기간 외 성과·비용 검증/가중치 채택 미완 |
| R14 | configured 7모드 실제 결과·receipt·replay pin·비게시 | 기본 CLI host 자동 배선 없음; supplied callbacks/typed loaders 필요 |
| R15 | 신규 wheel/sdist, clean 설치, exact allowlist·8스킬/미러/UI | Python3.14.6 Windows 한정; Codex arbitrary venv UI 발견·소스 내부 secret 전수 탐지 아님 |
| R16 | 이 별도 최종 세션의 실제 재실행·추가 ledger/시세 probe | R01–R17 모든 기능 완성이나 실서비스 운영 승인 아님 |
| R17 | 한국어 WAIT 5항목·저장/ref/hash/history·partial 보존 | 일반 분석 section 전체 한국어/ID 분리·가독성 및 전체 action numeric binding 미완 |

README와 IMPLEMENTATION_STATUS 최상단은 현재 제한과 일치한다. 아래 `Current Integrated Checkpoint (a1a41b0)`의 “working/current/in-progress” 문장은 **그 SHA의 역사적 상태**로 읽어야 한다. 최신 4e55a56/2a078da에는 WAIT 연결과 RC10–12 수정이 존재한다. 이 오래된 checkpoint 제목·문구는 후속 문서 정리 대상으로 남기며 신규 런타임 회귀로 보고하지 않는다.

## 재현 산출물·미실행

- 보존 독립 scripts: `docs/workflow/reviews/review_code_01_{first_pass_probes,interim_probes,b1f4514_probes,final_probes,dcd262a_probes,briefing_persistence_probe,refresh_binding_checks,rc12_roundtrip_checks}.py`.
- 신규 검사: `docs/workflow/reviews/verify_01_independent_checks.py`. 빌드 인터프리터로 실행; `--live`를 추가하면 위 두 공개 시장 경로를 조회한다. 기본 실행은 합성 입력만 사용한다.
- 전체 원 로그와 빌드/설치 재현 helper: 이 worktree `workspace/verify-01/`. 요약 출력은 `docs/workflow/reviews/verify_01_execution_evidence.txt`에 보존한다.
- 신규 검사 작성 중 출력 직렬화(mappingproxy)와 상태 필드명 오류를 고쳤다. 런타임/기존 테스트 오류가 아니며 수정 후 검사를 다시 실행하여 PASS를 확인했다.
- 실제 개인 DB/인증정보/주문, 계정·구독 확보, 원격 배포, 일반 동적 calendar, 모든 공급자 live, 정책 성과 검증, Python 3.11–3.13/다른 OS, Codex UI 자동발견은 미실행이다.

이 보고서와 인계만 최종 VERIFY의 판정이며, REVIEW-CODE-01은 별도 코드 검토 기록이다. 후속 runtime 변경이 있으면 이번 결과를 새 SHA로 소급 적용하지 말고 해당 범위를 다시 검증해야 한다.
