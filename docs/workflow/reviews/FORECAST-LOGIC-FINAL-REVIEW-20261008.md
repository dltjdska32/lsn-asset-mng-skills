# 예측 엔진 로직 보완 검토

## 결론과 범위

브라우저 ChatGPT가 구현하고 Codex가 설계·반례·독립 검토를 담당했다. 수신06 수정본의 네 P1과 정상 반복 import P2는 별도 독립 검토에서 해결을 확인했다. 고정 소스 `bb3091e75ac2e6106b483afe894264b8a23ef630`는 별도 새 최종 검증을 통과했다. 기존 저장소의 source 통합 commit은 `7b8cde08b37c307ffff5af9dd53c8977605f67d1`이다. 통합52파일의 Git blob을 수락소스와 대조했고 사용자 기존WIP7개 rawSHA는 보존했다. 원격push·배포·주문은 수행하지 않았다.

이 엔진의 목적은 펀더멘털 가치평가에 미래 시장가격의 별도 전망과 위험 정보를 더하는 것이다. 기업 성장률과 주주 수익률은 매입가격·희석·밸류에이션 변화 때문에 다르다. 기존 평가 이후 Capital Competition 이전에 미래 가격/수익률을 비교할 정보를 제공하려는 설계다. 현재 코드는 독립 엔진 및 연결 helper를 제공한다. 기존 7개 모드/시간별 브리핑/자동 Top10의 실제 자동 실행 완료를 뜻하지 않는다.

## 확인하고 보완한 로직

| 영역 | 원래 위험과 확인된 보완 |
|---|---|
| 기간·가격 기준 | aware 시간축, history와 cadence, target_date/horizon, 종목·통화·price basis를 검사. 오래된 월봉을 최근 5년 전망으로 재표시하지 않도록 거부. |
| 입력 OHLCV | Kronos의 관측시각/종가/길이가 실제 요청 history와 일치해야 추론. 미래 frame을 과거로 재라벨링하는 경로 차단. 원천 amount가 없으면 수치를 만들지 않고 UNAVAILABLE. |
| 펀더멘털 앵커 | 현재 적정가와 미래 terminal_price를 구분. 기준시각 미상/미래/잘못된 종목·통화·basis·status·숫자 앵커 제외. 채택 여부를 먼저 판정하여 부적합 앵커가 정상 모델을 탈락시키거나 출력 가격 기준을 오염시키지 않음. |
| XGBoost·LightGBM | 공개시각/단위/학습·검증·평가 cutoff 검사. target 이름·model ID·trained horizon·ME 12N cadence 정확 일치. 1년 목표를 5년 수익률로 해석하거나 59개월을60개월로 취급하는 경로 거부. 실제 native 학습→hash/save→fresh load→추론은 합성 자료로 확인. |
| 모델 출력 | Chronos와 Kronos의 모든 경로 단계/시간/가격·quantile 정합성 검사. 정상 Chronos 분기에서 np import 지역변수 오류 해결. 오류 모델 격리와 사용 가능한 구성요소 보존. |
| 시나리오·불확실성 | 시간·계산 기준과 기하 대표값/기대값 구분을 명시. ROIC/WACC 등을 반영하는 시나리오 helper와 Monte Carlo를 제공하나, 확률·구간의 실제 금융 보정 검증은 별도 미완료. |
| 출처 무결성 | exact pinned revision/weight hash/파일 inventory/경로·symlink/foreign module 검사. clean Git이어도 ignored 실행 코드의 import shadow를 거부. 정상 controlled Kronos import는 bytecode를 남기지 않고 반복/cold/동시 load 및 예외에서 Python 상태 복원. |
| 저장·감사 기록 | 공식 canonical run DB와 run/종목/기준시각 결속. active 앙상블 구성요소와 저장 모델의 실제 point/quantiles/status/semantics/provenance payload 일치 및 component links 검사. 불일치 시 atomic 거부. 현재 스키마가 저장하지 못하는 active observed_at은 조용히 버리지 않고 거부. |
| CLI·패키징 | point/value_kind 등 필요한 인자를 명시하고 assessment를 전달. Native E2E 및 명시적 package allowlist 보완. run schema upgrade와 personal/run DB 분리 유지. |

## 직접 확인한 검증

- 06 ZIP `af9010d27dd75f682369b03aeb416b266392bf9a3aaa0b036853c42b2d152f34`: 실제 다운로드/CRC/정확 inventory/31파일 최초 input-output SHA 일치.
- 06 집중 및 독립 반례: **200 PASS, 1 SKIP, 31.11s**. Windows symlink 권한으로 인한 해당 검사만 건너뜀.
- 05 전체 회귀: **846 PASS, 2 SKIP, 206 subtests PASS**. 이는05의 실제 결과이며06 최종 전체 검증으로 대체해야 한다.
- 별도 독립 검토는06에서 앞선4P1과P2를 닫았다. 실제 source verifier·loader를 사용하되 모델 클래스/weights 검증은 명시적으로 합성 대체한 import 테스트다.
- 별도 새 최종 검증 세션은 정확commit archive593개 tracked파일을 Git blob과 byte대조하고freshbuild 성공을 확인했다. 전체suite+9개readonlyprobe파일 **933 PASS, 2 SKIP, 206 subtests PASS, 178.46s**. 검사 후593파일과9probes변경없음. 두skip은Windows symlink권한, 검증인터프리터에wheel을설치하지않은상태의installed-skill검사다. 파일미러/패키지빌드검사는별도통과했다. 초기sandbox환경실패는최종보고서에기록했고환경을맞춘새전체실행으로확인했다.
- 기존root로통합후 forecasting/nativeE2E/schema **122 PASS, 1 SKIP, 25.50s**. root사용자WIP가있는전체트리933통과라고주장하지않으며,933은고정된새검증복사본결과다.

## 실전 사용 전에 남은 일

1. 실제 미국·한국·일본 금융 자료의 시점 기준 데이터셋. 공시 공개시각, 수정 재무제표, 상장폐지·생존편향, split/dividend/희석/통화 기준을 일관되게 검증해야 한다.
2. 실제 pretrained weights 추론 및 기간 외 검증. 파일 준비·출처 검증, 모형 API 정상 호출, 실제 금융 정확도는 서로 다른 증거다. 현재 테스트 통과는 실제 5년 뒤 가격의 예측력을 입증하지 않는다.
3. 5년 결과가 관측된 rolling/walk-forward 검증과 단순 기준모형·valuation-only 대비 비교. CAGR 오차/방향/구간 coverage·순위 안정성/비용·손실 지표와 가중치 선택 기간을 분리해야 한다.
4. 가중치와 불확실성의 금융 보정. 초기 anchor60% 등은 정책 초기값이며 검증된 최적값이 아니다. reliability override만으로 성능 검증·투자 승인 상태를 얻으면 안 된다. Monte Carlo 분포도 모델 예측 오류를 자동으로 보정하지 않는다.
5. authoritative 모드·브리핑·Capital Competition 연결의 end-to-end 검증. 현재 helper/API/독립 엔진과 자동 실행 완성은 구분한다. EXPERIMENTAL 상태와 unavailable/partial을 소비자가 보존해야 한다.

완성되면 기업 성장성, 매입가격 대비 기대수익률, 모델 간 의견 차이와 하락위험을 같은 기준으로 비교하는 데 도움을 준다. 이번 보완은 그 계산·시점·출처·저장 연결의 정확성을 높인 작업이다. 실제 금융 예측력과 자본배분 성과는 별도 자료와 검증이 필요한 상태다.

전체 설계 의도 A–I 감사는 `FORECAST-V7-DESIGN-AUDIT-20261008.md`, 수정별 재현은 `FORECAST-BROWSER-04/05/06-LOCAL-REVIEW-20261008.md`, 최종 결과는 `FORECAST-BROWSER-06-FINAL-VERIFY-20261008.md`에 기록한다.
