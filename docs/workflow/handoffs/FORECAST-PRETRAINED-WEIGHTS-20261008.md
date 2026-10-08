# 실제 사전학습 가중치 준비

사용자 요청: “가중치 내려받아야하자나”. 공개 HF 가중치 다운로드와 고정 SHA 검증을 실행했다. Runtime 코드 변경 없음. Hugging Face CLI 스킬 및 기존bootstrap사용. 최초직접실행은runtime PYTHONPATH부재로import실패했고, `PYTHONPATH=runtime;project` 지정 후전체bootstrap exit0/COMPLETE.

보관: `C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/pretrained-models`.

| 파일 | pinned revision | safetensors bytes | SHA256 |
|---|---|---:|---|
| Chronos-2-small | ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a | 111749048 | 492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd |
| Kronos-mini | f4e68697d9d5aed55cef5c96aabc3376bcad9f81 | 16440776 | a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c |
| Kronos-Tokenizer-2k | b22fb9cb30a2de2f77e8b617169cd756ba964a08 | 15842376 | b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717 |

실제weight3파일총144032200bytes. Config와각snapshot_manifest/PRETRAINED_MODELS.json생성. 엔진의 `verify_snapshot_manifest` 세폴더전부통과, `verify_kronos_source` 공식sourcecommit `67b630e67f6a18c9e9be918d9b4337c960db1e9a`/clean/ignored-executable검사통과.

공식 `hf cache verify <repo> --revision <pin> --local-dir <folder> --format json` 세모델각config/weight2파일공식checksum확인,exit0. Remote에서받지않은2파일은 `.gitattributes`와`README.md`임을공식API로확인. Localextra는HFdownload메타데이터및자체manifest이며모두엔진inventoryhash에포함됐다. 공식CLI검증후엔진snapshot검사재통과.

증빙: `workspace/cache/browser-gpt-forecast/pretrained-weights-verification-20261008.json`, `pretrained-download-20261008.log`, `hf-verify-*-20261008.log`.

한계: 기존review venv에는torch/chronos/transformers미설치. 실제가중치로모델을load/infer한것은아니다. 실제금융자료/5년OOS미검증. FinCast는기존defaultdisabled유지/미다운로드. HF공개모델은implicit token/telemetry비활성으로받았고개인DB/credentials/원격push/배포/주문미사용. Weight/sourcecache는Gitcommit대상에서제외.
