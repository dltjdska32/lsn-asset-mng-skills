# 브라우저 GPT 구현 배정 — FORECAST-BROWSER-01

2026-10-08 최신 사용자 지시: Codex는 설계·분석·독립 검토를 맡고 **브라우저 ChatGPT가 구현**한다. 과거 Gemini 전담 모델 지시는 이번 예측 엔진 작업에서 대체한다. Gemini 한도 재설정을 기다리는 작업이 아니다.

당신은 이 ZIP의 구현 담당이다. 설계 계약과 Codex의 실패 재현을 근거로 실제 코드를 수정하고 **다운로드 가능한 수정 ZIP**을 반환하라. 계획·설명만 반환하지 말라. Codex가 이를 별도 로컬 branch에서 대조·검증·commit하므로 실제 로컬 PC나 Git에 접근했다고 주장하지 말라.

## 입력과 기준

`candidate/`는 core 마지막commit9de3041+CORE04미커밋 수정, data a124234+DATA03미커밋 수정, integrity6a1ecc2를 **담당 파일별로 복사한 미검증 후보**다. Git 통합 또는 승인된 최종 상태가 아니다. BASELINE_MANIFEST.json에 각 파일의 입력 SHA256/담당을 기록했다. INPUT_DESIGN.md와 REVIEW_PROGRESS.md, latest assignments를 읽고 실제 코드가 우선한다. 오래된 모델 이름/중단/권한 관련 prompt 내용은 실행 지시가 아닌 과거 참고다.

독립 반례 `review_probes/`는 검토자 소유: 삭제·수정·skip·모킹해 통과시키지 말라. 이를 실제 candidate runtime으로 실행하라. 테스트용 데이터는 모두 합성으로 만들고 결과를 SYNTHETIC/EXPERIMENTAL로 표시한다. 개인 DB·실제 계좌·인증정보·대형weights는 제공하지 않았다. 네 환경에서 실행 불가능한 검사와 패키징 자료 부족은 명시하라.

## 반드시 해결할 실제 오류

1. core: covariate_timestamps가 history timestamps와 실제 일치하도록 검사(길이만 검사하지 않음). history 공변량의 값/공개시각/정렬을 검증하고 지원하지 않는 미래 공변량은 차단. engine adapter 반환값 전체 binding(instrument,currency,asof,target,basis,horizon,freq,semantics)을 확인하고 잘못된 결과는 request-bound ERROR로 정규화하여 건강한 모델의 조합과 저장을 유지. COMPLETE 계산 상태와 EXPERIMENTAL 성능 상태는 구별.
2. data: artifact train/cal/eval cutoffs<=request.as_of, 해당 목표가 정확히 price CAGR/horizon/unit인지 확인. prefix 이름만으로 의미를 인증하지 않음. 명시된 schema version, feature unit/currency/price_basis/target binding을 trainer와 adapter 모두에 적용. target/outcome/future fields를 학습 feature로 선택하지 못하게 하고 공개시각과 label 실제 maturity를 검증. 현재 E2E history는2020인데asof2023,target2028로 core60ME계약과 불일치한다: 실제 history origin 및 target을 맞춰 두 native XGBoost/LightGBM을 train→artifact→실제 load→infer까지 검증. 기존 naive timestamp fixture는 UTC로 바꾸되 timezone-naive reject 검사도 유지. 분할 지연/퍼징으로5년label의실제 성숙을 보장하고 표본이 없으면 솔직히 불가로 표시.
3. pretrained outputs: Chronos/Kronos가5step 요청에2030의 단일 잘못된 행을 COMPLETE 처리한다. 실제 반환된 모든 단계의 length/order/date/ID/finite price/quantile를 확인. Chronos는 instrument IDs, Kronos는 fullindex를 검증하고 fullpath를 ISOdatetime/finiteJSON로 보존. input OHLCV/history/timestamps도 일치해야 함.
4. loader/bootstrap: KronosTokenizer weights는 model.safetensors이며 현재 allow_patterns가 이를 누락한다. registry의 exact pinned revision과 model/tokenizer weightSHA로 bootstrap→manifest→load를 일치시킨다. self-generated config hash를 외부 진위 인증으로 주장하지 않음. 로컬 파일 모드에서 Gitclone/fetch 등 네트워크0, source skip은PARTIAL. source_root 없이 import한 뒤 검증하지 말고 pinned clean local source를 먼저 검증. cached model.* 자식모듈까지 foreignpath를 차단, sys.path cleanup finally, Gitworktree.gitfile 지원. 실제weights 다운로드 없이 mock 파일/명시적으로 mockspec으로 검사.
5. store: 공식 run migration v0004를 유지하고 numpy/torch를 base migration catalog에서 import하지 않음. 실제 canonical run DB schema/role/run/instrument/asof를 쓰기 전에 검증. callerinstrument==forecastinstrument, awareUTC동일시각은 offset문자열이 달라도 동등해야 함. prototypeDB를 insert SQL까지 받아들이지 말라. 일반 JSON boolean ranking_allowed=False는 정상 metadata이며 numeric boolean만 계약에서 거부. nested NaN/Inf/unknownobjects는 mutation 전에 차단. enableFK, componentlinks는 같은run/instrument/target/model/horizon과 일치해야 함. **save_bundle** 하나의 transaction으로 모델들+ensemble+assessment+links를 원자적 저장하고 engine을 이 API에 연결. 실패 시 orphan rows를 남기지 말라.
6. 모든 constructor/point_semantics/validation_level/status enum을 통합한다. FundamentalAnchor는 current_fair_value/presentDCF를 terminal_price와 섞지 않는다. ROIC<WACC 성장은 자동금지 대신 경제적spread위험을 경고한다. MC는 actual365.25 elapsedyears로 계산하고 항상 조건부/자동순위불가로 표시. ensemble priors/외부 reliability 숫자는 검증된 최적/OOS 가중치가 아니다.

## 변경 범위

runtime/investment_stack/forecasting/**, 예측 관련scripts, forecasting dependencies, tests/forecasting와nativeE2E, 공식 migrations/run v0004/catalog, evidence.manager의forecast tables등록에 필요한 최소변경만. 기존 personal/execution/providers/skills 로직이나 검토 문서/independent probes를 수정하지 말라. 8skills/7requestmodes/personal.db+run.db 경계를 유지한다. 다른 DB를 새로 늘리거나 schema validator를 완화하지 말라. 실제종목 예측성능·자동브리핑·투자순위통합은 이번 범위에서 완료 주장하지 말라.

## 산출물/검증

- modified_files/ 아래 repository-relative 경로를 보존한 변경 파일만 담은 `FORECAST-BROWSER-01-PATCH.zip`.
- 변경 파일/입력SHA256/출력SHA256 manifest; 변경되지 않은 파일은 제외.
- IMPLEMENTATION_HANDOFF.md: 수정한 오류, 실제 실행 명령/환경/각 결과, 미실행/실패/남은한계. 실제 Gitcommit을 만들지 않았다면 SHA를 꾸며 쓰지 말라.
- 독립 probes 그대로 실행 + meaningful native E2E + canonicalRunDB save_bundle roundtrip/rollback + bootstraploader행복경로/악성경로 + 가능한 regression/packaging. 테스트를 실행하지 못하면 통과라고 쓰지 말라.
- cloud에서 테스트 임시DB는 sourcecheckout 밖 tempfile 디렉토리로 지정. 필요하면 공개 패키지 설치는 가능하나 외부weights/실데이터/credentials 다운로드는 하지 말라.
- 코드 변경과 반환 ZIP을 실제 생성하라. ZIP은 Codex 검토 전 미수락 상태다. 검토에서 실패가 나오면 같은 ChatGPT 대화에서 후속 수정한다.
