# v7 자본배분 의사결정 정책

8개 Skill, 7개 Fixed Pipeline, Materiality Gate, freshness, append-only ledger,
personal.db/run.db 분리와 주문 없는 분석을 유지한다. 집중도는 위험 정보이며
자동 매도 신호가 아니다. 데이터가 뒷받침하면 4~6개 고확신 자산의 집중을 허용한다.
ETF와 현금도 비교 대상이며 집중도가 높다는 이유로 ETF를 자동 우선하지 않는다.

## 자본 경쟁과 분류

보유종목 전체와 명시된 신규 후보를 성장성, valuation, 사업·moat, 재무 건전성,
산업 성장, downside로 비교한다. 현금흐름·마진·부채·희석·자본집약도·고객집중·
유동성·thesis·이벤트·중복 노출과 대체 후보의 기회비용도 검토한다.
기본 가중치는 30/25/15/10/10/10%이며 검증된 승인 입력으로 변경할 수 있다.
각 점수는 출처와 평가 근거가 필요하다. 우선순위 점수는 예상 수익률이나 확률이 아니다.
자료 부족은 WATCH/관찰·순위 미확정이며 임의 점수로 채우지 않는다.

분류는 CORE_CONCENTRATION/핵심 집중, SECONDARY_GROWTH/보조 성장,
HOLD/보유, WATCH/관찰, REDUCE/비중 축소, EXIT_CANDIDATE/정리 후보이다.
감축·정리 후보는 valuation·기대수익·downside·대체 기회의 근거를 함께 제시한다.
비중 가이드는 핵심15~30%, 보조8~15%, 고위험·테마2~8%이며 고정 목표가 아니다.
1% 이하이며 확대 계획이 명시적으로 없으면 POSITION_TOO_SMALL_TO_MATTER를
표시한다. 테스트·옵션성·moonshot 의도가 있으면 예외이며 소액 자체로 자동 매도하지 않는다.

## 5년 시나리오와 재배치

검증된 현재 가격, 정규화 EPS/FCF/매출 기준, 성장 가정, terminal multiple,
희석, 배당을 출처·승인·시점·단위에 연결한다. 구현된 EPS 모델은
future EPS = EPS × ((1+growth)/(1+dilution))^5,
CAGR = ((future EPS × terminal multiple + 5년 누적 배당)/현재 가격)^(1/5)-1 이다.
Bear/Base/Bull 순서·연간 희석·배당 기간을 검증한다. 미지원 FCF/매출 모델이나
입력 부족이면 `5Y CAGR 확인 불가`이며 EPS 모델로 몰래 대체하지 않는다.
시나리오 CAGR은 확률 가중 기대수익률이 아니다. 임의 성장률·확률·목표가격을 생성하지 않는다.
신규 후보와 현재 가장 약한 보유종목을 비교하며 세금·수수료·환율·슬리피지
마찰비용이 없으면 재배치 순편익을 확정하지 않는다. 모든 결과는 검토 후보다.

## 실제 Level 3 Review

단일>25%(>30% 포함), Top2>50%, 신규자금 집중, 대규모 교체,
매우 높은 CAGR, 고성장 테마, 높은 지정학 위험은 실제 L3 실행을 요구한다.
task 생성이나 trigger만으로 완료하지 않는다. 같은 run의 계산·공식 자료를 사용해
반대 논리, 숨은 가정, 가격에 반영된 기대, 멀티플 압축, 성장 둔화,
고객·공급자 집중, 부채·희석, 규제·기술 대체, 마진 정상화, thesis breaker,
유동성·핵심 보유와의 상관·가장 강한 대안을 평가한다.
가정 없는 30~50% 성장 둔화는 검토 질문으로만 제시하며 숫자 예측을 만들지 않는다.
자료 공백은 topic별 UNAVAILABLE, 전체 PARTIAL로 저장·보고한다.
신규 집중·증액은 L3 완료 근거까지 대기하며 30% 초과 자체로 매도하지 않는다.

## 연결·보고 계약

`calculate_allocation_and_risk` 안에서 자본 경쟁·순위·집중 정당화·배분 후보를
계산하고 고정 `conditional_review → render_partial_aware_report`를 따른다.
별도 Skill이나 Generic DAG를 추가하지 않는다. SINGLE_ASSET_ANALYSIS에서
portfolio context를 명시적으로 요청하면 신규 후보와 보유종목의 동일 기준 비교를
붙인다. 검증된 포트폴리오·상대 입력이 없으면 비교 확인 불가를 표시한다.
같은 run의 evidence, calculation, approval, state_version, snapshot, cutoff를
검증하고 과거 결과를 freshness 검증 없이 재사용하지 않는다.

포트폴리오 보고서 앞부분 순서는 핵심 결론 → 자본 집중 우선순위 → 정리 우선순위
→ 유지/관찰 → 신규자금 → 자본 재배치 → 집중 Risk → 예상5Y CAGR
→ Thesis Breaker → Latest Material Events이다. 모든 보유자산을 포함하되
숫자 근거가 없으면 순위·후보·CAGR을 확정하지 않는다.
보고서에 계산 lineage, 시점·출처, 가정과 미확보 항목을 표시한다.

## ETF·Risk·현금·손익

ETF는 기준일 있는 공식 holdings/NAV를 실제 계산에 연결한다. 부분 holdings는
재정규화하지 않고 미분류·미확보 노출을 UNKNOWN으로 남긴다. 전체 총자산이
불명확하면 전체 포트폴리오 통과 비중을 계산하지 않는다. 펀드 간 중복은 각 펀드
기준 하한값으로 분리한다. 표시 정밀도로 weight 합계가1을 넘으면 원본은 보존하고
정밀도 모델 없는 계산을 보류한다. NAV를 순자산총액과 혼동하지 않는다.
전체 risk가 불가해도 실제 concentration/FX/자산군/확인된 가격 proxy를 실행한다.
proxy를 전체 공분산·승인 risk limit로 격상하지 않는다.
거래별 취득 FX·매수 비용·세금과 매도 순수입을 반영한다. 취득 FX가 없으면
현재 FX로 평단을 환산해 실제 원화손익이라고 하지 않는다. 예약금은 중복 차감하지
않으며 계좌·통화별 예수금/결제현금/매수가능/출금가능/담보를 분리한다.
스냅샷과 장부가 일치하지 않거나 결제·예약 커버리지가 없으면 매수가능금액은 보류한다.

## Automatic portfolio research conversion

PERSONAL_PORTFOLIO_ANALYSIS converts selected, fresh, same-run persisted
EQUITY_FUNDAMENTAL/EQUITY_VALUATION (or FUND) results into typed
CapitalCompetitionPolicyInputs inside the existing allocation stage. A request
need not inject capital_competition_policy_inputs. Every eligible held instrument
is processed, without a six-asset limit. Explicit overrides still require their
original evidence and approval receipts.

The bridge consumes documented normalized <dimension>_score research metrics.
Evidence score observations require assessment_rationale. Where explicit scores
are absent, revenue_growth, earnings yield (1/pe), roe, industry_growth_rate and
inverse debt_to_equity order the complete research cohort by midrank percentile.
Business quality needs a documented business_quality_score; industry growth
needs its own research observation and is never inferred from company revenue.
Missing/conflicting/unselected/stale/future evidence leaves an asset unranked.
These numeric comparisons are relative research priorities, not a complete moat,
financial-distress or downside model. Relative scores never themselves assign
REDUCE/EXIT/CORE or a budget. Source calculations, all normalization peer evidence
and cohort identities are persisted for reproducibility.

Missing explicit forecast scenarios does not suppress an evidenced research
ranking. It leaves 5Y CAGR and rotation benefit unavailable, keeps the report
PARTIAL and cannot authorize concentration or additional purchases. No forecast
or approval is fabricated. Legacy Policy B has no fixed 8% position cap or
10%-to-8% reduction trigger. Its cash floor and evidenced valuation/thesis checks
remain; a purchase budget requires a verified allocation risk budget and the
existing review/release checks.
