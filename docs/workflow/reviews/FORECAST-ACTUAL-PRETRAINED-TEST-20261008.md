# 실제 사전학습 모델 테스트

**후속 해결:** 아래는 수정 전 실패를 보존한 보고서다. FORECAST-BROWSER-07/08에서 시간대·실제 target_name 출력·nullable ID 누락·Kronos 경로 복원을 보완했다. 수락 소스 `8c993d4c0c5c7af090e52c8f462634f6f90e65c0`의 새 별도 최종 검증은 989 PASS / 2 SKIP / 206 subtests PASS, fresh wheel/sdist 및 실제 가중치 12/60개월 추론 PASS다. 루트 소스 통합 `bc0fd92df010ea1a01fa5960f01d5786f15278b0`. 최신 근거는 `FORECAST-BROWSER-08-FINAL-VERIFY-20261008.md`와 `FORECAST-BROWSER-08-INDEPENDENT-REVIEW-20261008.md`를 참조한다. 금융 예측 정확도는 여전히 미검증이다.

판정: **부분 성공. 실제 모델 연결 코드의 보완이 필요하다.** 내려받은 safetensors로 로딩과 추론을 실행했고 모델이나 가중치를 모의 구현으로 대체하지 않았다. 입력은 합성 월봉이며 실제 금융 성능 검증은 아니다. 런타임 코드는 수정하지 않았다.

## 환경과 실행

Source HEAD `c398550`(코드통합 `7b8cde0`, 문서추가이후). 별도venv `workspace/cache/forecast-inference-venv`,Python3.12. 기존reviewvenv보존. 공식PyTorchCPUindex와PyPI에서설치. CPU2threads/seed7/HF_HUB_OFFLINE=1/TRANSFORMERS_OFFLINE=1. 모델참조는downloadedlocal절대경로.

- torch2.14.1+cpu, chronos-forecasting2.3.2, transformers5.19.0, huggingface_hub1.33.0,einops0.8.1.
- 최신numpy2.5.3/pandas3.0.6첫실행에서Chronos실패후프로젝트검증버전numpy2.3.5/pandas2.3.3으로맞춰재실행. 같은실패재현.
- truststore0.10.4를해당venv에설치후프로젝트PYTHONPATH상태의pipcheck **No broken requirements found**. 전체환경lock `workspace/cache/browser-gpt-forecast/inference-environment-lock-20261008.txt`.
- 합성월봉120개(2016-10~2026-09),가격/volume/amount,12개월및60개월추론. 실제개인DB/금융자료/주문/네트워크추론없음.

읽기전용실행helper는 `workspace/cache/browser-gpt-forecast/actual_pretrained_smoke.py`, `actual_chronos_diagnostic.py`. 프로젝트runtime코드나모델코드를고치지않았다.

## 결과

| 단계 | Chronos-2-small | Kronos-mini |
|---|---|---|
| 실제weight load | PASS, Chronos2Pipeline | PASS, KronosPredictor/tokenizer |
| 기존프로젝트adapter 12개월 | ERROR | COMPLETE, 약0.16s |
| 기존프로젝트adapter 60개월 | ERROR | COMPLETE, 약0.72s |
| 공식pipeline직접12/60개월 | UTC로정규화한naiveprovider입력에서PASS,각12x9/60x9출력 | 기존adapter추론이공식predictor를호출 |
| 새adapter반복load | 실행불필요 | PASS |
| 로딩후sys.path복원 | 변화없음 | 실패: `../`추가잔존 |

추론값은합성입력에대한값이므로실제종목의예상주가/CAGR로사용하지않았다. Chronos직접추론성공은아래프로덕션adapter실패를성공으로바꾸지않는다.

## 수정 필요 사항

### P1: Chronos aware timestamp와실제API불일치

`runtime/investment_stack/forecasting/adapters/chronos2.py:81`에서awaretimestamps를그대로context/future에전달한다. chronos2.3.2 `df_utils.normalize_df:129`가 `df[timestamp_column].to_numpy().view('int64')`를실행해aware타임스탬프의objectarray에서 `TypeError: Cannot change data-type for array of references.` 발생. 최신/프로젝트지정numpy·pandas양쪽재현.

공식pipeline에UTC-aware입력은12/60모두같은실패. 진단helper에서이미UTC인입력을provider경계에서UTC-naive로표현하면실제weights로12/60모두정상추론한다. 수정은request PIT/timezone검증을유지하면서UTC정규화후provider형식으로변환하고반환시각을UTC로결속해야한다. 원시naive요청을허용하는방식으로해결하면안된다.

### P1: Chronos target_name를숫자열로오인

`chronos2.py:111`의numeric_columns가id/timestamp외모든열을float로변환한다. 실제공식반환열은 `id,timestamp,target_name,predictions,0.1,0.25,0.5,0.75,0.9`. `target_name`은문자열`target`이다. 직접실제반환DataFrame에현재adapter의선택·변환을적용해 `could not convert string to float: 'target'` 재현.

시간대문제를해결해도이분기에서다시실패한다. targetidentity를검증하고numeric가격/quantile열을명시적으로선택해야한다. 임의문자열열을모두무시하여identity결속을약화하면안된다.

### P2: 실제Kronos import후Python경로잔존

고정된공식 `kronos-source/model/kronos.py:9`가 `sys.path.append('../')`를실행한다. `adapters/kronos.py:91`finally는자신이prepend한sourcepath만제거하여`../`가남는다. 실제model `_load`전후path비교로확인. 추론·반복load는정상이지만성공/실패에서원래path전체를보존하는계약과다르다. 현재로더의bytecode차단과무결성검사는여전히통과했다.

## 증빙과 범위

- `actual-pretrained-smoke-pinned-20261008.json/.log`: 최종어댑터실행,전체FAILED(exit2).
- `actual-chronos-diagnostic-20261008.json/.log`: 실제APIaware실패/UTC-naive성공/target_name변환실패와traceback.
- 설치logs 및 환경lock은같은packet폴더.
- 실행후3snapshot inventory/weight SHA 및Kronossourcepin/clean/ignored코드검사다시PASS. 기존사용자WIP7개SHA불변확인.

이전933개검사통과는명시된local/syntheticmock범위의실제결과다. 그검사는실제Chronos반환target_name와공식source의sys.path변형을재현하지않았다. 이번actualweights테스트가더넓은범위의남은연결결함을확인했다. 이번요청은테스트이며구현을성공으로위장하거나runtime코드를직접수정하지않았다.
