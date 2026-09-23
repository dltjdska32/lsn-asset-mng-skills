# 초기 구현·환경 확인 기록

확인일: 2026-09-23. 담당: 총괄 Codex. 코드 기준: `3d4a95ba33d582f67a99de7b410b160e62645961`.
이는 초기 진단이며 독립 검토나 최종 검증 통과 보고가 아니다.

## 시작 상태

- 작업 폴더: `C:/Users/lsn/lsn-asset-mng-skills`.
- 브랜치: main. 시작 시 `git --no-optional-locks status --short --branch`는 `## main...origin/main`만 출력했다. 원격 fetch는 하지 않았다.
- 저장소와 확인한 상위 경로에 기존 AGENTS.md가 없었고 docs/workflow도 없었다.
- 기존 skills 원본은 8개이며 routing enum과 planner는 7개 모드를 정의한다.
- README의 v1.3.1, ARCHITECTURE의 구현 미착수, IMPLEMENTATION_STATUS의 2026-08-14/272개 테스트, pyproject의 패키지 0.1.0은 서로 다른 기준 기록이다. 새 완료 상태로 해석하지 않는다.
- 설계 원문과 저장소 ARCHITECTURE는 바이트 동일하지 않다. 외부 문서는 Markdown 서식이 있고 저장소 문서는 상당 부분 평문이다. 두 자료를 설계 입력으로 보존하며 완전한 의미 동등성을 선언하지 않는다.

## 코드와 합성 입력으로 재확인한 결함

아래는 `python -X utf8 -B -`로 표준입력 스크립트를 실행했다. `sys.path`에 runtime을 추가하고 메모리 내 ProviderObservation/ProviderResult와 가짜 transport만 사용했다. 실제 개인 DB, 파일 DB, 외부 금융 API, 계정 credential을 사용하지 않았다. 기존 소스나 테스트 파일은 수정하지 않았다.

| 요구사항 | 현재 코드 위치 | 합성 사례·실제 출력 | 의미 |
|---|---|---|---|
| R01 | `deep_research.py`의 `_current_price` | 분석 2026-09-23 09:00 UTC, 관측 2026-08-14 09:00 UTC, USD 100 → freshness STALE, current_price 100 | 과거값의 계산 유입 재현 |
| R02 | `deep_research.py`의 `_normalize_financials` | 같은 공개시각·등급, FY2024 매출 100/FY2025 매출 200을 반대 순서로 입력 → revenue 100/200, 경고 없음 | 기간과 동률 선택 계약 누락 재현 |
| R03 | `_explicit_scale`, `_unit_scale`, `_normalize_metric_value` | value 10, unit USD, unit_scale invalid 또는 -1000 → Decimal(10), 경고 None | 잘못 명시한 배율이 1로 대체됨 |
| R04 | `providers/adapters.py`의 SecCompanyFactsAdapter → 정규화 | us-gaap/Revenues/units/USD에 val 200·기간·filed·form·accn 제공 → 관측값 1개, metrics {}, 경고 () | 공식 중첩 구조가 계산 지표로 변환되지 않음 |
| R05 | `providers/execution.py`, `ProviderResult.usable` | stale 값을 가진 first와 second 공급자 → 호출 목록 ['first'] | 결과 적격성 전에 fallback 종료 |
| R14 | `routing/router.py` | '삼성전자 매수해도 될지 분석해', '매수하지 말고 삼성전자 분석해' → ASSET_UPDATE | 투자 질문·부정문 분류 오류 |
| R14 | `routing/router.py` | '삼성전자 10주 샀어. 보고서 갱신해' → REPORT_REFRESH | 복합 요청의 거래 처리 단계가 가려짐 |

라우팅 재현은 원장 변경을 실행한 것이 아니다. 기존 posting 검증 경계는 별도로 존재한다.

## 추가 코드·테스트 확인

- `cli.py`의 공개 명령은 route/plan/check다. `pipelines/planner.py`는 불변 단계 목록을 반환한다. `tests/acceptance/test_phase8_request_modes.py`는 라우팅·단계와 non-posting 경계를 주로 확인하므로 7개 모드의 결과물 생성 완료 증거가 아니다.
- `calculations/valuation.py`에는 명시적 DcfAssumptions와 여러 자산 모델이 있다. 그러나 `deep_research.py`의 실시간 equity 입력 구성은 DCF 가정을 전달하지 않는다. 시나리오별 적정가·민감도·판단까지 완성됐다고 볼 수 없다.
- `EvidenceResearchStore`는 비교 metadata 일부를 사용하지만, live 재무 정규화는 별도로 provider_results를 재선택한다. 실제 입력과 selected evidence의 일치 검증이 설계에 필요하다.
- FreshnessEngine은 시장 CLOSED/HOLIDAY와 market_session_date 존재로 LAST_VALID_CLOSE를 반환하는 경로가 있다. 최신 완료 거래일 여부·거래소 캘린더의 별도 검증을 계약에 포함해야 한다.
- 기존 WebResearchAdapter/Bundle은 주입된 검색 결과 경계다. 시장별 실제 페이지 조회 구현·접근 성공과 구별해야 한다.
- runtime/tests/config/skills의 정확한 RSI/MACD/OHLCV/13F 이름 검색에서 해당 기능 구현은 확인되지 않았다. 기존 risk/alternative의 일반 시계열 계산이 전체 차트·13F 구현을 대신하지 않는다.
- `scripts/sync_agent_skills.py`는 8개 SKILL.md만 복사한다. `agents/openai.yaml` 동기화는 해당 스크립트에 없다.

## 이번에 실행한 제한적 검증

다음 기존 unittest 모듈을 표준입력 Python runner에서 실행했다. 결과: **22 tests, OK**, 실패·오류 없음.

- tests.unit.test_routing
- tests.unit.test_phase5_equity_valuation
- tests.unit.test_phase4_providers
- tests.unit.test_v131_korean_display

이 테스트 통과와 위 결함 재현은 동시에 성립한다. 예를 들어 SEC 기존 테스트는 AVAILABLE과 source_tier만 검사하고 실제 fact-to-calculation 변환을 검증하지 않는다. 새 경계 사례를 별도 회귀 검증에 추가해야 한다.

전체 테스트, 설치 후 Windows 검증, wheel 설치 검증, 실제 수집→브리핑, 모든 17개 항목 완료 검증은 이번에 실행하지 않았다. 이전 검토 보고서의 287개/58개 오류 및 상태 문서의 272개 통과를 이번 실행 결과로 재사용하지 않는다.

## 로컬 설정 확인

- python 경로: `C:/Users/lsn/AppData/Local/Python/pythoncore-3.14-64/python.exe`, 버전 3.14.6.
- 이 인터프리터에서 `importlib.util.find_spec('tzdata')`는 None. 패키지는 설치하지 않았다. 실제 IANA timezone 동작 확인은 후속 준비 검사 대상이다.
- `Get-Command py`에서는 launcher를 찾지 못했다. `python`으로 동일 인터프리터를 지정해야 한다.
- README는 외부 의존성이 없다고 하지만 pyproject는 Windows tzdata를 선언한다. 설치 문서 수정 대상이다.
- 기본 PowerShell 경유 Python 출력에서 cp949 인코딩 오류를 한 번 확인했고, UTF-8 모드(`-X utf8`)로 읽기 출력을 복구했다. 파일 인코딩은 변경하지 않았다.
- `C:/Users/lsn/AppData/Local/agy/bin/agy.exe --help`는 종료코드 0. models, --model, --mode(plan/accept-edits), --sandbox, --print, --output-format을 실제 도움말에서 확인했다. 설정을 변경하거나 Gemini 모델을 실행하지 않았다.
- READY 응답 성공은 사용자 보고다. 선택 모델·도구 실행 권한·동시 세션 한도는 아직 검증하지 않았다. 도움말 존재만으로 권한이나 sandbox 효과를 입증하지 않는다.

## 다음 설정 안내: 한 단계만 제시

첫 안내는 PowerShell에서 다음 조회를 실행하고 결과 중 모델 목록/현재 선택 표시를 확인하는 것이다. 로그인·권한 오류면 실제 오류를 바탕으로 그 다음 한 단계만 안내한다.

```powershell
& 'C:\Users\lsn\AppData\Local\agy\bin\agy.exe' models
```

모델 식별 이후 별도 단계로 제한된 임시 폴더의 읽기·쓰기·명령 권한 확인, 단일 실행 성공, 격리된 2개 세션의 동시성 실증을 진행할 계획이다. 실제 병렬 수는 성공/차단/한도 응답을 보고 정하며 현재 3개 동시 실행 가능을 전제하지 않는다. 모든 명령 무조건 승인·전역 권한 완화는 하지 않는다. 이후 Python 가상환경·의존성도 같은 인터프리터로 준비한다. 이 문단은 후속 계획이며 지금 실행 지시가 아니다.

## 참조 자료 검토의 한계

총괄은 두 설계 문서·이전 검토·현재 8개 스킬·관련 runtime/tests/config와 지정 참조 스킬들의 방법론을 확인했다. Daloopa 21개 전부의 제목·분석 구성과 대상 파일 존재를 확인하고 주요 계산 본문을 추가 확인했다. DESIGN-01에서 지정 참조 35개 본문을 검토하고 design.md §10에 각 방법론의 반영/보류를 기록했다. 총괄은 이 추적표를 통합 확인했다. 소스 전체를 복제하거나 참조 스킬의 벤더 명령을 실행하지 않았다. 하위 references/scripts 전체의 별도 검증은 이번 범위에 포함하지 않았다.

Codex worktree 생성 절차는 [공식 작업 폴더 문서](https://learn.chatgpt.com/docs/environments/git-worktrees)를 참고했으나 이번 대기 현상의 원인은 확인되지 않았다. 실제 복구와 세션 식별자는 tasks.md에 남겼다.
