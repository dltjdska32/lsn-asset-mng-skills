# PACKAGE-01-RC08 — sdist version-check repair

## Assignment

- Finding: R15 P2 RC08 from independent review `b1f4514`.
- Base: latest integration commit `39e6508`.
- Branch: `codex/r15-sdist-rc08`.
- Scope: packaging test, sdist manifest/allowlist, and this handoff only.

## Change

- Added `ARCHITECTURE.md` to the explicit sdist manifest and exact sdist allowlist. The version test reads this file to verify the canonical architecture label.
- Added a regression test that unpacks the built sdist into a temporary directory and executes the packaged version metadata test there.
- No skill source, runtime source, personal DB, or credentials were changed or accessed.

## Verification

- Built wheel and sdist using the existing `C:\Users\lsn\lsn-asset-mng-skills\.venv\Scripts\python.exe` build environment with `python -m build --wheel --sdist --no-isolation`; no dependency downloads.
- `python -m unittest tests.test_packaging`: 7 tests passed, 1 expected installed-wheel-only check skipped in the build environment. This includes exact artifact allowlists and the unpacked-sdist subprocess regression.
- `git diff --check`: passed.

## Not run

- Full repository test suite; this repair is constrained to R15 packaging.
- Wheel installation validation, provider calls, or any DB operations.
