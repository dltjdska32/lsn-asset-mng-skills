# 설계 결정과 미결정

버전: DESIGN-2026-09-23-v0.1. 작업 DESIGN-01. 요구사항 REQ-2026-09-23-v1.
코드 기준: `3d4a95ba33d582f67a99de7b410b160e62645961`. 갱신: 2026-09-23.

이 기록은 사용자가 이미 정한 경계와 설계자의 제안을 구분한다. 2026-09-23 후속 지시가 첫 실행 제한을 해제하고 이 설계에 기반한 구현·검토·최종 검증을 승인했다. 아래 첫 실행 한도는 역사 기록이며 현재 범위는 AGENTS.md와 tasks.md가 우선한다. 투자 정책의 미확정 수치는 임의 확정하지 않는다.

## 이미 정해진 경계

| ID | 상태/출처 | 내용 |
|---|---|---|
| B01 | 사용자/AGENTS 지침 | 기존 8개 스킬·7개 모드·고정 파이프라인·personal.db/run.db 분리를 기본으로 유지 |
| B02 | 사용자/AGENTS 지침 | 설계·개발 독립 검토·최종 검증은 다른 새 세션. 이번은 설계만. 런타임 optional reviewer와 별개 |
| B03 | 사용자/AGENTS 지침 | 개인 데이터·credential을 공유 문서/프롬프트/로그/저장소에 기록하지 않음; 실제 개인 DB 개발 테스트 금지; 자동 주문 제외 |
| B04 | DESIGN-01 복구 배정 | 동일 원본 폴더에서 문서별 단일 작성자. design/decisions/DESIGN-01 handoff만 편집. 후속 Gemini 병렬은 별도 branch/worktree 필수 |
| B05 | 사용자 요구 R08–13 | 차트·13F 가중치와 신호·안전마진·위험/규모 수치는 미확정. 참조의 예시값을 production 기본값으로 채택하지 않음 |
| B06 | 사용자/AGENTS 지침 | skills/가 원본, mirror 동기화는 승인된 후속 구현. 설정 안내는 총괄이 한 번에 한 단계씩 제공 |
| B07 | 2026-09-23 사용자 후속 지정 | Gemini 구현 모델 선택은 **3.8 Flash, High**(사용자 표기: `3.8flash high`). 실제 CLI 모델 식별자·High 옵션 지원 여부는 별도 확인 |

## 제안과 미결정 목록

| ID | 상태 | 제안/질문·이유 | 영향·검증 | 결정 주체/시점 |
|---|---|---|---|---|
| D01 | 검토 대기 | 차트·13F는 기존 자산 분석 내부 runtime 모듈로 배치; 별도 스킬·모드 불필요 | 8개 유지. fundamental은 기관 보유 문맥, valuation/개인위험은 결과 소비, report는 출처 설명. 새 스킬 필요 시 발견성/동기화/invariants 영향 재검토 | 설계 독립 검토 후 사용자/총괄, 착수 전 |
| D02 | 검토 대기 | 목적별 EligibilityDecision/SelectedInputSet 공통화. provider 응답 성공과 계산 가능을 분리 | R01–05/07/12/16; 기존 SelectedEvidence 호환·재선택 제거·permutation/동률충돌 테스트 | 공통 계약 담당 지정 후 승인 |
| D03 | 미확정 | typed payload를 기존 run metadata/observations에 연결하는 최소안. 필요한 경우 run-only migration/컬럼·테이블 확장 | FinancialFact/Bar/13F 크기·조회/계보 요구 검증. 개인 schema 변경 없음. 기존 migration checksum 보존; physical schema 결정 없이는 병렬 구현 금지 | CONTRACT-01, 설계 검토 시 |
| D04 | 미확정 | 공개시각 분리, date-only 구간 상한 기준 적격성, 정정 vintage 보존 | SEC filed 날짜를 자정 공개시각으로 발명 금지. 13F acceptance/정정 체인·guidance 대상기간 fixture 필요 | A/C와 계약 담당, 공통 계약 확정 전 |
| D05 | 미확정 | 시장/목적별 DELAYED·LAST_VALID_CLOSE 허용과 캘린더 검증 | 현재 기본 20분/1일을 자동 승계하지 않음. 장중/시간외/휴장/거래정지/24x7 구분, 실제 마지막 세션 확인 | 사용자 목적 + B/A 검증, 가격 계산 활성화 전 |
| D06 | 미확정 | R06 후보(공식·네이버페이증권·Investing.com·현지 대체)의 순서/coverage 확정 | 접근·필드·지연·권한·호출 제한을 실제 확인해야 함. 미확인 도구/API 이름은 구현 성공 아님 | B, 승인된 live 실증 시 |
| D07 | 미확정 | indicator seed/공식은 design §4 제안. n/EMA/MACD/RSI 기간·추세/돌파 파라미터·신호 가중치는 추후 결정 | 최소 표본·0 분모·prefix invariance, 비용 포함 기준 모델 대비 기간 외 검증. 미승인 시 계산 설명만 가능, 매매 신호 없음 | 사용자/검토자, R08 활성화 전 |
| D08 | 미확정 | 투자 review 이름을 유지할지 충돌 방지 이름으로 변경할지 | 변경하면 원본·mirror·UI·EXPECTED_SKILLS·문서·테스트를 함께 수정; 8개 수는 유지. 지금 이름 변경 안 함 | 사용자/총괄, R15 구현 전 |
| D09 | **명시 원문 DCF 규약**(2026-09-28 사용자 완료 지시, 작업 트리 미커밋) | 행동용 적정가는 보수·기준·낙관 세 시나리오가 각각 `explicit_dcf_assumption_v1` 원문 excerpt의 필드·값과 저장 계산의 재계산에 맞을 때만 연다. 고정 beta/ERP/terminal/성장률 기본값은 만들지 않는다. 적정가는 시장 예측 가격이 아니다. 민감도는 원문에 충격 가정이 있을 때만 계산한다. URL·제공자 이름만으로는 verified가 아니다 | 원문이 없거나 일부 시나리오만 있으면 적정가 Money는 열리지 않는다. FCFF/FCFE 정의가 원문에 없으면 현금흐름 종류를 추정하지 않고 그 적정가를 만들지 않는다 | 이 작업의 합성 결속. 라이브 공시 진위는 범위 밖 |
| D10 | 미확정 | 13F schema vintage·value scale·amendment scope·identity mapping·기관군 | 공개 원문/XSD와 실제 fixture로 확인; SH/PRN/put-call·confidential omissions/중복 관리자 처리. 법규 최신성/접근성은 이번 미확인 | C와 계약 담당, R12 구현 전 |
| D11 | 미확정 | 13F 점수 feature/감쇠·가중치·채택 허용치와 point-in-time dataset | 사전 등록한 baseline/기간 외/비용/누출/coverage 기준 모두 충족 후 채택. 현재 UNVALIDATED, 매매 반영 금지 | 사용자/독립 검토자, R13 검증 전후 분리 |
| D12 | **사용자 B 균형형 선택**(2026-09-28); 산식은 `61fd2eb`에서 독립 검증. 저장 원문·고정 원장이 다시 맞을 때만 조건부 수량 | 개별 주식의 검증된 기준 적정가에 대한 80%/75%/70% 세 단계, 각 회차 예산 1/3. 종목 상한 8%, 예약금 제외 투자현금 하한 10%. 비중 **10% 초과**면 8% 복귀 축소 검토, 검증된 낙관 적정가의 **1.2배 이상**이면 보유량 1/3 축소 검토. 투자 논지 훼손 시 추가매수 중지 | 호출자가 만든 정책 객체나 URL만으로는 보고서 숫자를 열지 않는다. 등록 파서가 시세·DCF·수수료·호가·거래 단위·논지를 재추출하고, 고정 원장의 시가·FX·부채·비상자금·예정 지출·미체결 예약이 맞을 때만 `CONDITIONAL_NON_POSTING`. 아니면 해당 수치는 WAIT. 주문·원장 반영 없음. 13F 점수는 매매 조건 아님 | 합성 사례는 이 작업 트리에서 숫자를 낸다. 라이브 시세·실제 개인 금액·기간 외 13F는 여전히 WAIT |
| D13 | 검토 대기 | 고정 dispatcher+execute API, UPDATE_THEN_ANALYSIS의 제한된 순차 envelope | 7개 모드 유지, 질문/부정/주문≠거래 사실. draft 제외, receipt 후 pin, idempotency, refresh non-posting | R14 담당/독립 검토, 통합 전 |
| D14 | 미확정 | 설치·릴리스·package/schema/config 버전과 UI mirror 배포 범위 | Windows venv 같은 python/tzdata·wheel·config·8개 discovery 확인. 참조 패키지/벤더 설치는 별도 승인 범위 | 총괄/R15, 실제 설치 안내는 한 단계씩 |
| D15 | 모델 선택 확정 / 실행 환경 미검증 | 사용자는 Gemini **3.8 Flash, High**를 지정했다(B07). READY는 사용자 보고이며 실제 CLI 모델 식별자·High 지원·도구 권한·동시성은 아직 미검증 | 지정 모델을 임의 변경하지 않음. A/B/C 3개 동시 실행 가정 금지. 전역 권한 완화 금지; 격리된 설정 실증 결과에 맞춰 병렬도 결정 | 사용자+총괄 SETUP-01 |
| D16 | 검토 대기 | 공통 파일 담당 CONTRACT-01을 먼저 지정하고 A/B/C를 전용 파일로 분리 | registry/factory/DB/exports/config는 단일 writer. deep_research는 A→통합 순차 소유권 인수. 테스트 파일 포함 | 총괄, 구현 배정 전 |
| D18 | **2026 거래일 스냅샷 추가**(2026-09-29) | 9월 고정 구간 밖은 대기였다. 공식 휴장표가 있는 평일을 세션으로 둔다 | NASDAQ·NYSE는 Nasdaq Trader 2026 휴장과 11/27·12/24 13:00 조기종료. KRX는 공휴일·근로자의 날·12/31과 기존 추석 경계를 뺀 평일 09:00–15:30. JPX는 JPX 2026 휴장표를 뺀 평일 09:00–15:30. 일본 시세는 Yahoo `.T` 본문을 재파싱한다. 긴급 임시 휴장은 표에 없다. 13F는 매매 조건이 아니고 개인 금액은 생성하지 않는다 | 사용자 지시. 해시 일치는 거래소 서명이 아니다 |
| D17 | **검토 전용으로 구현, D12 행동 숫자는 유지**(2026-09-29) | 급락·알림·뉴스 중복·데이터센터·고객 집중·가이던스 차이·변동성 참고가는 승인된 80/75/70 산식과 충돌하므로 진입가를 대체하지 않는다. 사용자는 선택지 없이 구현을 지시했다 | 행동 가격은 계속 원문 기준 적정가의 80/75/70이다. 검토 임계값은 세션 수익률 −5% 이하, 5세션 −8% 이하, 또는 1봉 −3% 이하이면서 직전 거래량 중앙값의 2배 이상이면 `DROP_REVIEW`다. 변동성 참고가는 실현 표준편차와 5% 중 작은 값만큼만 보여 주고 주문가가 아니다. 고객 집중은 공시 합계의 20% 이상이면 표시만 한다. 빠진 필드는 WAIT다. `refresh_market_bodies`가 참일 때만 미국·한국 시세 본문을 미선택으로 저장한다. 일본 공식 거래일은 묶지 않고, 13F는 검증 플래그가 있어도 `DISABLED`다. 개인 금액은 생성하지 않는다 | 사용자 지시. 이 검토 값은 조건부 수량을 WAIT로 되돌리지 않는다 |

## 참조에서 그대로 채택하지 않은 판단

- 일부 Daloopa 문서는 beta/Rf/ERP/terminal/peer 값을 sensible defaults로 채운다. 현재 요구 R01–05/09에 따라 출처 없는 시장값은 제외하고 가정도 provenance를 요구한다.
- guidance의 +1분기 또는 Q4→다음FY는 보편 규칙이 아니다. 원문 대상 기간을 계약에 포함한다. 정성 전망을 임의 숫자로 환산하지 않는다.
- OCF-capex를 항상 FCFF로 보거나 EV에서 net debt 차감 후 cash를 다시 더하는 예시는 사용하지 않는다. 모델별 현금흐름과 가치 bridge를 검증한다.
- diluted weighted shares를 시총용 기말 shares로 자동 대체하거나 EPS/주식 수를 분기 합산하는 방법은 수정한다.
- 이익 전년비 증가를 consensus beat로, 과거 평균 beat를 실제 시장 whisper로, 기관 신고 평가액을 매입원가로 해석하지 않는다.
- 차트/13F/재무 지표의 고정 우열·집중도·매매 수치와 무조건 낙관/비관 확률은 검증 전 보류한다. 지표 공식의 수학적 상수와 투자 판단 임계값은 구분한다.
- 참조의 브랜드/HTML·Excel·PPT 산출물·전용 도구 사용 지시는 방법론 분석 대상이다. 설치/네트워크/파일 생성 지시로 실행하지 않았다.

## 변경 관리

2026-09-23 D17 (총괄 기술 확정, 사용자 자율구현 승인 범위): REVIEW-DESIGN-01 새 Codex의 직접 검토 중간 결과를 채택하여 `assignments/CONTRACT-01.md`에 실행 계약 v0.2를 고정했다. stdlib-only strict versioned typed codec, finite Decimal 정규 문자열, EXACT/DATE_INTERVAL/UNKNOWN 공개시점, coherent SlotSpec coverage, 슬롯별 bound selected snapshot/hash, 단일 transaction·expected revision CAS·불변 selection history를 기존 run JSON에 저장한다. 기존 market FK selection/evidence 상태는 호환 projection이다. 개인 schema와 기존 migration은 변경하지 않는다. 정책 미승인 UNAVAILABLE, 명시 가정 검증된 경우만 CONDITIONAL. B/C는 계약 commit과 테스트 후 시작. 이는 투자 가중치·위험수치 확정이 아니다. D01/02/03/04/13의 기술적 구현 방향을 이 범위에서 해소하며 최종 검토가 제기하는 추가 문제는 추적한다.

설계 변경은 결정 ID, 요구사항, 이유, 변경 contract/API/파일, 검증 영향, 새 버전/hash, 수신할 작업 ID를 남긴다. 총괄이 검토된 사본을 각 worktree에 전달하고 수신 확인 전 종속 구현을 진행하지 않는다. requirements/tasks/기준 commit 배정은 총괄 소유이며 설계자가 덮어쓰지 않는다. 승인 상태를 자동으로 APPROVED로 올리지 않는다.
# D18 — 격리 초안 구현과 공통계약 인수를 분리

2026-09-23 총괄 실행 결정. CONTRACT-FIX-03 fdd64f0에서 MarketQuote/Bar/Holding13F의 원19개 메모리반례는 통과했으나 저장/evidence/fullscope 및 gate/codec 잔여감사로 전체계약 인수는 미완료다. A가 공통계약을 계속 수정하는 동안 B/C의 독립 source parser·기술지표·13F 비교 구현을 fdd64f0의 명시적 **미인수 초안 기준**에서 병행한다. B/C는 contracts/storage/공통gate를 편집하지 않으며 임시 DTO 우회나 검증 약화를 하지 않는다. 후속 확정 계약과 충돌하는 연결은 소유자에게 요청하고 최종 계약으로 갱신·재검증한 뒤에만 통합한다.

이유: 기존 일괄 의존성이 파서와 수학식 구현까지 저장 재개 검증에 묶어 대기시키고 있었다. 파일 소유권과 실제 소비 의존성을 나누어 세 Gemini 세션이 독립 구현을 병행하게 한다. 영향: 계약 변경에 따른 B/C 재연결 검증이 필수이며 초안 테스트 통과를 공통계약 인수·전체 완료로 보고하지 않는다. 8스킬/7모드/DB분리·미승인 정책 차단 기준은 변하지 않는다. 사용자 추가 승인 없이 진행하는 기존 자율 구현 범위의 일정 조정이다.
