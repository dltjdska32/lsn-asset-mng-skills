# Distribution artifact allowlist

This is the path allowlist for the Python wheel and source distribution. `MANIFEST.in` and `setup.py` implement it; `tests/test_packaging.py` compares complete built artifact file lists to it. Any intentional artifact change must update this document and the exact-list test together.

## Wheel (`investment_stack-0.1.0-py3-none-any.whl`)

Allowed files are exactly:

- `investment_stack/**/*.py` from `runtime/investment_stack/`.
- The five wheel metadata files: `METADATA`, `WHEEL`, `entry_points.txt`, `top_level.txt`, and `RECORD` under `investment_stack-0.1.0.dist-info/`.
- Exactly `config/freshness.yaml`, `config/materiality.yaml`, `config/providers.yaml`, `config/reconciliation.yaml`, and `config/web_research.yaml` under `investment_stack-0.1.0.data/data/`.
- For each of the eight names below, exactly `SKILL.md` and `agents/openai.yaml` under both `skills/<name>/` and `.agents/skills/<name>/`, installed as wheel data files under `investment_stack-0.1.0.data/data/`.
- Also `references/capital-allocation-policy.md` under both trees for exactly
  investment-orchestrator, personal-asset-analysis, valuation, investment-report,
  and review. These references extend the existing skills; no ninth skill is added.

## Source distribution (`investment_stack-0.1.0.tar.gz`)

Allowed project files are exactly:

- `ARCHITECTURE.md`, `README.md`, `pyproject.toml`, `setup.py`, generated `setup.cfg`, and `MANIFEST.in`.
- `docs/workflow/deployment-allowlist.md` and `scripts/sync_agent_skills.py`.
- `scripts/build_verified_distribution.py`, `scripts/capture_market_data.py`, `scripts/run_personal_portfolio.py`, and `scripts/run_asset_analysis.py`: clean verified build, actual HTTP capture, and configured portfolio execution.
- The five explicitly named `config/*.yaml` inputs above.
- All `runtime/investment_stack/**/*.py` source files and setuptools' six generated `runtime/investment_stack.egg-info/` metadata files (`PKG-INFO`, `SOURCES.txt`, `dependency_links.txt`, `entry_points.txt`, `requires.txt`, `top_level.txt`).
- No `tests/` directory or testing source files. The local checkout keeps all tests for offline validation; neither source distributions, wheels, nor public/GPT runtime archives carry those files. `MANIFEST.in` uses an explicit final `prune tests` to override default setuptools test discovery.
- The optional local forecasting input lock `requirements-forecasting.txt`, manual bootstrap utility `scripts/bootstrap_pretrained_models.py`, CLI `scripts/run_pretrained_forecast.py`, native training `scripts/train_tabular_forecaster.py`, and `scripts/walk_forward_tabular.py`. Bootstrap is **manual only**, may contact Hugging Face/Git if explicitly invoked without `--local-files-only`, and is **never called automatically by analysis or inference services**. `--local-files-only` verifies existing local pinned Kronos source without clone/fetch/checkout. No weights or checkpoints are distributable. The wheel includes only the new `runtime/investment_stack/forecasting/**/*.py` source; optional dependencies are *not* installed by default.
- For each of the eight skill names below, exactly `SKILL.md` and `agents/openai.yaml` under both `skills/<name>/` and `.agents/skills/<name>/`.
- The same five explicit policy references listed above, under both skill trees.

The allowlist is exact at the file-path level. It excludes local credential values, `.env` files, database files and sidecars, workspace/run data, logs, caches, virtual environments, Git metadata, bytecode, keys, and certificates. The five YAML files are shipped as explicit input resources under the wheel's `sys.prefix/config/`; the CLI does not auto-load them as global defaults, and call sites must choose a config path explicitly. In particular, values such as `config/freshness.yaml`'s 20-minute/one-day age fields are not thereby approved for all price purposes. `providers.yaml` contains the name of an optional environment variable, not its value. This path check does not scan allowed text files for accidental secret literals, so code review still applies.

## Skill inventory and discovery boundary

The authoritative names are `investment-orchestrator`, `fundamental-analysis`, `valuation`, `fund-analysis`, `alternative-asset-analysis`, `personal-asset-analysis`, `investment-report`, and `review`. `review` retains its current name; D08 remains unresolved, so no rename or alternate UI name is introduced. `scripts/sync_agent_skills.py` copies only from `skills/` to `.agents/skills/` and `--check` verifies inventory, exact allowed files, and byte equality.

The wheel installs config inputs under `sys.prefix/config/` and the two skill trees under `sys.prefix/skills/` and `sys.prefix/.agents/skills/`. The clean-install test verifies that the five config resources, eight definitions, and eight UI metadata files are present; the skill source/mirror files are byte-identical. That confirms packaged skill payload discovery by path only; it does not establish that Codex automatically scans an arbitrary virtual-environment prefix. Repository-local Codex discovery is through the workspace's `.agents/skills/` mirror.

## Version meanings

| Identifier | Current value | Meaning |
|---|---:|---|
| Canonical architecture | `v1.3` | Frozen design label in `ARCHITECTURE.md`; not a Python release number. |
| Python distribution and runtime | `0.1.0` | `pyproject.toml` and `investment_stack.__version__`; kept in sync. |
| Contract envelope | `0.2` | Typed contract format version; evolves independently of the package. |
| Personal database schema | `4` | Latest personal migration number. |
| Run database schema | `4` | Latest run migration (forecast tables); personal schema remains independent. |
| Config files | per-file | YAML files carry their own `version`; `RunContext.config_version` is context metadata, not a distribution version. |

No release mapping between architecture `v1.3`, the `v1.3.1` hardening description in README, and Python distribution `0.1.0` is defined. This package task does not create a release, change migration history, or claim that a schema/config version was upgraded.

- `scripts/run_equity_screening.py`: explicit public equity universe screening; no personal holdings bundled.

## Local-only verification and public artifact boundary

Existing `tests/test_packaging.py`, `tests/test_r15_skill_sync.py`, the native
XGBoost/LightGBM E2E, and all AI forecasting/source/calendar/PIT regressions
remain in local checkouts. They are intentionally not copied into public
wheel/sdist artifacts or new operational runtime bundles. Run the local
packaging suite **against a newly built wheel and sdist** before publishing.
The sdist version check extracts the actual distribution into a temporary
directory, then compares `pyproject.toml`, runtime `__version__`, generated
`PKG-INFO`, and architecture metadata there without importing a `tests/` tree.
`tests/test_packaging.py` checks exact runtime/config/skills/script allowlists,
rejects sensitive paths, and independently verifies the complete absence of
`tests/` paths in both distributions.

`.gitignore` now excludes new `tests/` files and local temporary output,
while preserving all earlier credential/DB/cache exclusions. **Existing tracked
test files remain in working trees and the Git index until the integration
owner executes `git rm --cached` for the approved test paths.** This patch
neither deletes tests nor modifies Git history or the index.

`scripts/build_verified_distribution.py` only imports setuptools and reads
runtime sources; it neither imports `tests` nor needs test sources inside
sdist. Its source remains explicitly allowlisted. The local verification
suite is a release prerequisite, not an sdist runtime dependency.

No investment logic, schema, model, workflow, policy, or dependency changes
are authorized by this publication-only adjustment.
