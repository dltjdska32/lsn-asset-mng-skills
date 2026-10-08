# FORECAST-BROWSER-06-FINAL — independent frozen-source verification

Verdict: **PASS for the approved local/synthetic scope**, with the two explicit skips below. This is a new final-verification session, separate from the acceptance reviewer. Prior success reports were not substituted for execution. No runtime fixes, shared-task edits, commits, remote actions, real personal DB access, or model downloads were performed.

## Frozen source and exactness

- Accepted branch: `codex/forecast-browser-gpt`.
- Commit: `bb3091e75ac2e6106b483afe894264b8a23ef630`.
- Git tree: `7bf76d1a2ea8624dd13814b8f43b36f6be8fd8ef`.
- Input base: `baf846e7ac1a5184727294d1705cf11d514e50f5`; original project base: `2bfec11cf9e1dc26f9426791b2a9d064915e2965`.
- Design/contract: `docs/workflow/FORECAST-LOGIC-DESIGN-20261008.md`, F01–F07.
- Received ZIP SHA256 independently confirmed: `af9010d27dd75f682369b03aeb416b266392bf9a3aaa0b036853c42b2d152f34`.

A new copy was created at `workspace/cache/forecast-browser-final-verify` using `git archive` of the exact commit. Archive worktree-converted bytes were replaced with their exact `git cat-file --batch` blob bytes. All **593 tracked files** were checked against the SHA1 Git blob hash, including the original `.gitignore`. A new empty local Git context was initialized solely for the existing check-ignore tests; no verification-copy commit was made.

Nine existing `independent_*probes.py` files were copied unchanged from the accepted worktree. Their SHA256 inventory is recorded in `workspace/cache/forecast-browser-final-verify/workspace/cache/final-source-verification.json`. After all tests, every tracked file still matched its Git blob, all nine probes remained unchanged, and the accepted source worktree had empty `git status --porcelain` at the frozen commit.

## Direct execution and results

Interpreter: `C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-review-venv/Scripts/python.exe`, Python **3.12.14**. Existing dependency environment was not modified.

Fresh package build, before the successful full test run:

```powershell
$env:PYTHONPATH='C:/Users/lsn/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages'
$env:PYTHONDONTWRITEBYTECODE='1'
& C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-review-venv/Scripts/python.exe -m build --no-isolation
```

Working directory was the verification copy. **Both wheel and sdist built successfully** using the existing official setuptools dependency path. Build log: `workspace/cache/forecast-browser-final-verify/workspace/cache/final-build.log`.

Fresh artifacts:

| Artifact | SHA256 |
|---|---|
| `dist/investment_stack-0.1.0-py3-none-any.whl` | `46661ec910b76ca7119586127ab3a3b107fb1d9f548ff8a8dc40c0c0f109f14a` |
| `dist/investment_stack-0.1.0.tar.gz` | `b3fa26e7e25ad8670f47f4c5d2a0d79a832e3def9b874f99efa6a81007624e84` |

The complete successful test command was:

```powershell
$verify='C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-browser-final-verify'
$env:PYTHONPATH="$verify/runtime;$verify;$verify/workspace/cache;$verify/tests/forecasting"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:FORECAST_REVIEW_ROOT=$verify
& C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-review-venv/Scripts/python.exe -m pytest tests workspace/cache/independent_contract_probes.py workspace/cache/independent_data_probes.py workspace/cache/independent_integrity_probes.py workspace/cache/independent_runner_probes.py workspace/cache/independent_browser_positive_probes.py workspace/cache/independent_input_binding_probes.py workspace/cache/independent_acceptance05_probes.py workspace/cache/independent_exact_cadence05_probes.py workspace/cache/independent_repeat_load06_probes.py -q -ra --basetemp=C:/Users/lsn/AppData/Local/Temp/forecast-browser06-final-pytest-elevated
```

Result: **933 passed, 2 skipped, 11 warnings, 206 subtests passed in 178.46 seconds**, exit code 0. Full log: `workspace/cache/forecast-browser-final-verify/workspace/cache/final-pytest-elevated.log`.

This includes all original repository tests, forecasting regression tests, the nine independent probe modules, fresh distribution allowlist checks, and `tests/test_e2e_forecast.py` native XGBoost/LightGBM training-save-load using synthetic PIT inputs. Kronos repeated/cold import, exceptions, four-thread loads and hostile ignored bytecode/source cases use synthetic local Git/model fixtures. These fixture Git commits are temporary test data, not project commits.

Skips:

1. `tests/forecasting/test_browser02_regressions.py:167`: the OS could not create the test symlink (`WinError 1314`, symlink privilege unavailable).
2. `tests/test_packaging.py:203`: installed skill discovery requires wheel data installed under this interpreter's `sys.prefix`. The shared interpreter was deliberately not mutated. Fresh wheel/sdist inventory and exclusion checks did run and pass.

Warnings: ten existing pandas regex capture-group warnings from runner timestamp checks and one pandas deprecated invalid-frequency-string warning from an intentional rejection probe. No test failure was reported in the successful run.

## Retained initial attempt and environment limitation

The initial full attempt began before the fresh build and ran inside the restrictive sandbox. It produced many filesystem failures and was stopped at 47% after a focused diagnostic confirmed `Path.resolve(strict=True)` on a synthetic temporary `run.db` raised `WinError 5` through the storage identity check. Its partial log remains at `workspace/cache/forecast-browser-final-verify/workspace/cache/final-pytest.log`; it has no completion count and is not reported as passing.

The focused diagnostic command was `python -m pytest tests/forecasting -x -q --basetemp=C:/Users/lsn/AppData/Local/Temp/forecast-browser06-final-diagnose`, with the same test environment. It returned **1 failed, 13 passed, 1 skipped in 13.84 seconds**. The failed case was `test_active_links_and_inactive_model_audit[adapters0-active_expected0-all_expected0]`, caused by that sandbox path-access denial.

No code was changed to accommodate the denial. The authorized synthetic verification was rerun with normal Windows filesystem access after the fresh package build, and the entire suite passed as recorded above. All temporary DBs were outside the source tree; no actual personal DB was used.

## Scope of acceptance

The frozen approved source has no newly observed material regression in the executed F01–F07 contract, PIT/cadence, isolation/provenance, persistence, synthetic model workflow or packaging checks. The forecast subsystem remains experimental where empirical evidence is absent.

This result does **not** establish financial forecast accuracy, real-data 5-year OOS performance, authentic pretrained-weight inference, automatic integration of the seven request modes, or Top10 investment ranking readiness. No real market-data validation or empirical calibration was performed. Those remain separate unfinished validation work.
