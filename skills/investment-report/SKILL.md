---
name: investment-report
description: Produce evidence-based investment reports with pinned as-of state, calculation lineage, confidence, and explicit partial or unavailable sections. Use for final single-asset, comparison, portfolio, scenario, thesis-review, and refreshed reports.
---

# Investment Report

1. State the analysis date, timezone, pinned state version when applicable, and report availability.
2. Separate evidence, calculations, interpretation, and proposed monitoring actions.
3. Cite the evidence identifiers and source timestamps used for each material conclusion.
4. Display stale, conflicting, partial, and unavailable inputs prominently.
5. Never label an unverified or stale value as a current price.
6. Keep rumors from changing the base case; label news confirmation state.
7. Include risks, thesis breakers, monitoring signals, and model limitations.
8. Present strategy as analysis, never as an executed order or posted transaction.

## v7 portfolio decision sections

Apply [the capital allocation policy](references/capital-allocation-policy.md).
Lead portfolio reports with its ten ordered decision sections. Include every
holding, actual review/calculation lineage, and explicit unavailable rankings or
5Y CAGR. Do not promote concentration warnings into automatic reductions or
make an ETF the default answer.


## v1.3.1 user-facing quote/report rules

9. User-facing status/action labels must be Korean. Keep internal enum/database values in English for compatibility, but render `UNKNOWN/PARTIAL/LIVE/DELAYED/STALE/BUY/HOLD/SELL/Confidence` as clear Korean labels.
10. For a current-price claim, do not stop at the first failed, untimestamped, stale, or invalid source. Retry appropriate fallback sources; use `확인 불가` only after fresh/current evidence still cannot be verified.
11. Every displayed price must carry its data date/time and market/freshness state. Old observations must never be presented as today's current price or used as a current-price calculation input.
12. When multiple comparable sources disagree, verify timestamp/session/source authority and never average the conflicting prices. Preserve conflict lineage.
13. Separate quote retrieval from news research. Prefer market-appropriate quote sources; web research is fallback and must satisfy timestamp/freshness rules.
14. When current price remains unavailable, explain the reason in Korean (for example `오늘 시세 확인 실패`, checked-source count when known, and latest verified data time when known) rather than exposing an internal English status code.

## 실험적 AI 예측 표시 경계

동일 run의 `AI_FORECAST` 계산 및 저장 model/ensemble receipt가 검증된 경우만 AI companion(모델별 point, disagree, 조건부 MC, 가격 CAGR, 시간축/출처, 실패·누락)을 보여줍니다. 가격 CAGR에 배당/비용/세금/환율을 포함하거나 기존 EPS 5년 시나리오 CAGR/자본 경쟁 점수·순위·회전 승인으로 표시하지 않습니다. `ranking_allowed=false`, OOS 정확도 미검증을 유지합니다. 모델이 없거나 source 적격성이 없으면 수치 없는 UNAVAILABLE을 같은 종목 행에 유지합니다.
