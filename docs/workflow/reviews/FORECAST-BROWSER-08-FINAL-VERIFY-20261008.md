# FORECAST-BROWSER-08 별도 최종 검증 (2026-10-08)

판정: **승인된 수정 범위 PASS**. 독립 검토와 분리된 새 최종 검증 세션이 고정 소스의 새 복사본에서 직접 실행했다. 이전 통과 보고를 실행 대신 사용하지 않았다. 소스 구현, 공유 tasks 수정, 프로젝트 commit, 원격 작업, 모델 다운로드, 실제 개인 DB 접근은 수행하지 않았다.

## 고정 소스와 실행 후 불변성

- 작업: FORECAST-BROWSER-07 + 08, ACTUAL-01/02/03. 계약: `docs/workflow/FORECAST-BROWSER-07-CONTRACT-20261008.md`.
- 원본: `C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-browser-gpt`, branch `codex/forecast-browser-gpt`.
- 고정 commit: `8c993d4c0c5c7af090e52c8f462634f6f90e65c0`.
- Git tree: `3db5a62bdda0a2b108d850b36937d0217350fe22`.
- 새 복사본: `C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-browser08-final-verify`.

`git archive` 후 `git cat-file --batch`의 정확한 blob bytes로 595개 tracked 파일을 재작성하고 Git blob SHA1을 전부 확인했다. 원래 `.gitignore`를 포함하며 check-ignore 테스트를 위한 빈 로컬 Git context만 초기화했다. 복사본 commit은 만들지 않았다. 기존 9개 independent probes, 새 독립 검토 28개 반례의 `independent_actual07_probes.py`, 실제 가중치 helper까지 11개 파일을 SHA256으로 원본과 일치 확인했다.

전체 실행 후 **595 tracked 파일, 10개 probes 및 helper 불변**, accepted 원본은 고정 HEAD에서 `git status --porcelain` empty였다. 루트의 보호 대상 사용자 WIP 7개는 기존 SHA256 manifest와 모두 일치했다. 증거: 복사본 `workspace/cache/final-source-verification.json`, `final-after-integrity.log`.

## 새 패키지 빌드와 전체 회귀

기존 환경을 변경하지 않고 `C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-review-venv/Scripts/python.exe` (Python 3.12.14)를 사용했다. 새 복사본을 cwd로 다음을 실행했다.

```powershell
$env:PYTHONPATH='C:/Users/lsn/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages'
$env:PYTHONDONTWRITEBYTECODE='1'
& C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-review-venv/Scripts/python.exe -m build --no-isolation
```

기존 official setuptools dependency 경로를 사용한 **wheel/sdist 빌드 PASS**. 로그: 복사본 `workspace/cache/final-build.log`.

| 새 산출물 | SHA256 |
|---|---|
| `dist/investment_stack-0.1.0-py3-none-any.whl` | `a316f99699f635b38e35dc4473054c17c98c71c5c59f87e38bf21e08059b86ca` |
| `dist/investment_stack-0.1.0.tar.gz` | `5c73180675aa3764ce64487821e4acce70927f4302d7ff5ad8c42e64d7c3f930` |

```powershell
$verify=$PWD.Path
$env:PYTHONPATH="$verify/runtime;$verify;$verify/workspace/cache;$verify/tests/forecasting"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:FORECAST_REVIEW_ROOT=$verify
$probeFiles=Get-ChildItem workspace/cache/independent_*probes.py | ForEach-Object {$_.FullName}
& C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-review-venv/Scripts/python.exe -m pytest tests @probeFiles -q -ra --basetemp=C:/Users/lsn/AppData/Local/Temp/forecast-browser08-final-pytest
```

**989 passed, 2 skipped, 11 warnings, 206 subtests passed in 195.56s**, exit 0. 로그: 복사본 `workspace/cache/final-pytest.log`. 실행은 승인된 require_escalated로 정상 Windows 파일 접근을 사용했다. 모든 임시 DB는 OS Temp에 생성된 합성 테스트 자료다.

두 skip은 기존 범위 제한이다. `test_browser02_regressions.py:167`은 Windows symlink privilege 부재(WinError 1314), `test_packaging.py:203`은 공유 interpreter sys.prefix에 wheel 설치를 하지 않아 설치된 스킬 검색을 실행하지 않았다. 새 wheel/sdist allowlist, 스킬 포함/제외 및 원본 패키지 검사는 통과했다. 경고 10개는 기존 pandas regex capture group 안내, 1개는 의도적 잘못된 frequency 거부 입력의 deprecated 문자열 안내다.

## 실제 사전학습 가중치 직접 실행

별도 기존 환경 `C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-inference-venv/Scripts/python.exe`를 변경하지 않았다. torch 2.14.1+cpu, chronos-forecasting 2.3.2, transformers 5.19.0, huggingface_hub 1.33.0, numpy 2.3.5, pandas 2.3.3. CPU 추론이며 GPU 검증은 하지 않았다.

cwd는 새 복사본, PYTHONPATH는 해당 복사본의 runtime/root만 지정했다. `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, telemetry 및 implicit token disabled=1. `FORECAST_PRETRAINED_MODELS=C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/pretrained-models`, `FORECAST_SMOKE_OUTPUT=actual-pretrained-smoke08-final.json`으로 byte-exact helper `workspace/cache/browser-gpt-forecast/actual_pretrained_smoke.py`를 실행했다. 로컬 실제 weights를 사용했으며 pipeline/predictor mock, 새 다운로드, 공식 소스 수정은 없었다.

| 실제 실행 | 결과 |
|---|---|
| Chronos2Pipeline 실제 로딩 | PASS; sys.path 내용/list identity 및 bytecode flag 동일 |
| Chronos 월봉 12/60단계 adapter 추론 | 둘 다 COMPLETE, ModelForecast.validate PASS |
| Chronos Asia/Seoul 요청 12/60단계 | 둘 다 COMPLETE |
| KronosPredictor 실제 model/tokenizer 로딩 | PASS; sys.path 내용/list identity 및 bytecode flag 동일 |
| Kronos 월봉 12/60단계 adapter 추론 | 둘 다 COMPLETE, ModelForecast.validate PASS |
| Kronos 새 adapter 반복 로딩 | PASS |
| Kronos model 모듈 cold import, bytecode 기본 false 복원 | PASS; 경로 list identity 및 flag 복원 |
| 세 모델 snapshot manifest 및 고정 공식 소스 | PASS; 전체 suite 완료 후 재검사도 PASS |

실제 helper 결과 **FINAL PASS**, exit 0. 로그: 복사본 `workspace/cache/final-actual-pretrained.log`; 구조화 결과: `workspace/cache/browser-gpt-forecast/actual-pretrained-smoke08-final.json`. 후검사 로그: `workspace/cache/final-model-post-integrity.log`. Kronos source pin `67b630e67f6a18c9e9be918d9b4337c960db1e9a`를 유지했다.

## 판정 범위

이번 수정은 Chronos UTC-naive provider boundary, 실제 target_name 스키마 결속 및 pandas nullable ID/target_name 누락 거부, Kronos sys.path/bytecode 상태 복원에 대해 새 독립 반례와 실제 local weights 연결 시험을 통과했다. 기존 전체 회귀 및 패키지 검증에서도 실패를 발견하지 못했다.

입력은 **120개 합성 월봉**이다. 실제 종목 가격 정확도, 5년 out-of-sample 성능, 수익률/불확실성 보정, GPU 실행, seven request modes 자동 통합 및 Top10 투자 순위의 실증 타당성은 검증하지 않았다. helper의 `financial_accuracy=NOT_EVALUATED`를 유지한다. 합성 가격 출력은 실제 투자 예측으로 제시하지 않는다.
