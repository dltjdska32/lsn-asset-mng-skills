# PACKAGE-01 — R15 packaging and install handoff

## Assignment

- Task: `PACKAGE-01`
- Requirement: `REQ-2026-09-23-v1`, R15 (installation, skill discovery, and distribution allowlist); R16 untouched except CLI smoke coverage.
- Design: `DESIGN-2026-09-23-v0.1`, §8. Referenced D08 and D14; neither is marked resolved by this task.
- Assigned baseline: `fd4355e5d4ed13f4aeacd34eacb7e40e74431342`.
- Branch: `codex/luna-r15-package-01`.
- Worktree: `C:\Users\lsn\.codex\worktrees\luna-r15-package-01\lsn-asset-mng-skills`.
- Allowed ownership: `README.md`, `IMPLEMENTATION_STATUS.md`, `ARCHITECTURE.md`, package data/build allowlist (`MANIFEST.in`, `setup.py`), `scripts/sync_agent_skills.py`, R15 tests, and this handoff. `pyproject.toml` and all skill content were read and verified but did not require modification. Runtime/A/C-owned source was not edited. The authoritative skills and `.agents/skills` mirror remain unchanged.

## Implementation

- Strengthened the source-to-mirror sync script to require exactly the eight current skill directory names, exactly `SKILL.md` and `agents/openai.yaml` per skill, and no symlinks. It rejects extra files/directories rather than silently ignoring them. `--check` remains read-only; normal sync repairs missing/changed expected mirror files.
- Added an exact distribution allowlist in `docs/workflow/deployment-allowlist.md`. `setup.py` ships the runtime `.py` package, five individually named YAML config resources, and exactly the eight skill definitions plus UI metadata from both `skills/` and `.agents/skills/`. `MANIFEST.in` names the five configs, R15 sync/install artifacts, exact skill files, and explicit exclusions for DB/sidecars, environment/credential files, logs, workspace/cache/run data, venvs, Git metadata, bytecode, and keys/certificates.
- The five configs install at `<venv>\config\`. The CLI does not automatically select them as global defaults. `materiality.yaml` and `reconciliation.yaml` were loaded through their existing explicit-path loaders from the installed wheel; other config files were checked for exact package placement, not claimed as actively loaded by the CLI.
- No skill source or UI metadata was renamed or rewritten. D08 remains unresolved, and the `review` skill name remains unchanged. Source and mirror inventory and bytes match.
- Clarified README and architecture/status docs: architecture `v1.3`, README's `v1.3.1` hardening description, Python distribution/runtime `0.1.0`, contract envelope `0.2`, personal/run DB schema migrations `3`/`2`, and individual config versions are distinct identifiers with no release mapping. No schema or contract migration was made.
- `pyproject.toml` already declares `requires-python >=3.11`, conditional Windows `tzdata`, and `truststore>=0.9.1`; those declarations were verified, not changed.

## Build and same-interpreter verification

- Build environment reused: existing Windows Python `3.14.6` environment with `build==1.6.1`, `setuptools==84.0.0`, and `wheel==0.48.0`.
- Built `investment_stack-0.1.0-py3-none-any.whl` and `investment_stack-0.1.0.tar.gz` with `python -m build --wheel --sdist --no-isolation`. The isolated target venv used Python `3.14.6`. No package index access or dependency download was used: installed `tzdata==2026.4` and `truststore==0.10.4` payloads were reused from the existing local venv, then the target venv's own `Scripts/python.exe -m pip install --no-index <wheel>` installed the package.
- The same target interpreter ran `pip check` (no broken requirements), imported package/distribution version `0.1.0`, loaded `America/New_York` and `Asia/Seoul` using Windows timezone data, ran the R15 tests, loaded explicit config paths, ran `scripts/sync_agent_skills.py --check`, and invoked the installed Windows console command.
- Final focused tests: `tests.test_packaging` and `tests.test_r15_skill_sync` — **10/10 passed**, no skip in the wheel-installed target venv. These compare the complete wheel/sdist file paths with the allowlist; verify the eight source/mirror names, required UI metadata keys and byte equality; and check installed files under `sys.prefix/skills`, `sys.prefix/.agents/skills`, and `sys.prefix/config`.
- Console CLI smokes: `investment-stack.exe check --project-root .` passed all 11 architecture invariants; `plan THESIS_REVIEW --json` returned its fixed six-step plan; a synthetic empty `REPORT_REFRESH` execute request returned `PARTIAL` with the three expected missing inputs during preflight and no DB/handler was provided. This confirms CLI startup and fail-closed preflight, not execution of a configured investment mode.
- `git diff --check` passed.

## Commands for the integrator

Use the same target interpreter for install, checks, tests, and smoke commands:

```powershell
$BuildPython = 'C:\path\to\existing-build-venv\Scripts\python.exe'
& $BuildPython -m build --wheel --sdist --no-isolation

python -m venv .venv-wheel-check
$VenvPython = (Resolve-Path .\.venv-wheel-check\Scripts\python.exe).Path
$Wheel = (Resolve-Path .\dist\investment_stack-0.1.0-py3-none-any.whl).Path
& $VenvPython -m pip install $Wheel
& $VenvPython -m pip check
& $VenvPython -B -m unittest tests.test_packaging tests.test_r15_skill_sync
& $VenvPython scripts\sync_agent_skills.py --check
$Cli = (Resolve-Path .\.venv-wheel-check\Scripts\investment-stack.exe).Path
& $Cli check --project-root .
& $Cli plan THESIS_REVIEW --json
'{}' | & $Cli execute --mode REPORT_REFRESH --run-id package-smoke --json
```

If target dependency wheels are not cached, stop and report what is missing before downloading; this task used existing local dependency payloads only.

## Not run / limitations

- Full repository unittest suite and root-wide integration suite were not run by this task. They remain for the integrator at the integrated commit.
- Python 3.11–3.13 were not tested; the package metadata's `>=3.11` claim remains broader than this Windows run's empirical coverage.
- The installed `.agents/skills` and UI metadata payloads were verified at the venv prefix. Codex UI automatic discovery from an arbitrary venv prefix was not tested; repository-local discovery is verified through the workspace `.agents/skills` tree.
- No provider live request, OAuth/MCP/vendor setup, credential value, personal DB, or run DB was used. No external service authorization is claimed.
- The current build exports config files as resources but does not make all YAML entries active policies. In particular, including a freshness configuration resource does not resolve D05 or approve its values universally.
- No remote publish, push, deployment, merge, or schema change.
