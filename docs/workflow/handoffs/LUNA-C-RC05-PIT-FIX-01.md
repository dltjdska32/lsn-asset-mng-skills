# LUNA-C-RC05-PIT-FIX-01 Handoff

## Scope

- Requirement areas: R12 filing/holding-period comparison inputs and R13 point-in-time scoring.
- Base commit: `ec800489823f061bcf278608633618d288def3f5` (integrated C work including FX-risk fix).
- Branch: `codex/luna-c-rc05-pit-fix-01`.
- No personal database or account data was used.

## Changes

- Comparison records now retain optional prior/current `PublicAvailability` evidence, supplied to `compare_portfolios` by the caller.
- `compute_institutional_features` only scores comparable records when both filings have verified availability at or before `as_of`, and the current report period is not after the cutoff date. Invalid, unknown, absent, or future availability is excluded.
- If no eligible comparison remains, feature values stay empty, `is_point_in_time=False`, and `score_status="UNAVAILABLE"`.
- Valid evidence still produces only `UNVALIDATED` features. The 13F trade gate remains `DISABLED`.
- Added self-contained synthetic cutoff/publication regression tests in `tests/unit/test_r12_r13_pit_scoring.py`.

## Verification

Passed (34 tests):

```powershell
$env:PYTHONPATH='runtime'
python -m unittest tests.unit.test_r12_r13_pit_scoring tests.unit.test_r13_validation tests.unit.test_r12_sec_13f.TestSec13FSubmissionsParsing tests.unit.test_r12_sec_13f.TestSec13FInformationTableXmlParsing tests.unit.test_r12_sec_13f.TestAmendmentChainSynthesis tests.unit.test_r12_sec_13f.TestPortfolioComparison tests.unit.test_r12_sec_13f.TestSourceVintageAndMissingRowCoverage
```

`git diff --check` passed.

Not run: `TestPointInTimeCutoffFiltering.test_date_only_conservative_cutoff` because this Windows Python environment has no `tzdata` package for IANA `America/New_York`; the isolated run failed before exercising project logic. The full R12/R13 suite was therefore not completed.

## Remaining integration detail

Callers constructing comparisons must pass the verified availability for both filing snapshots to `compare_portfolios`. If they omit it, scoring now fails closed as `UNAVAILABLE`. This branch does not enable 13F trade consumption.
