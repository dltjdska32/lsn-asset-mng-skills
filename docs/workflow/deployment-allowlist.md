# Distribution artifact allowlist

This is the path allowlist for the Python wheel and source distribution. `MANIFEST.in` and `setup.py` implement it. On 2026-10-08 the user requested a production-source cleanup: tracked tests and one-off verification artifacts were removed. The former exact-list tests remain in Git history; the cleanup build is inspected directly against this allowlist. Historical verification reports describe their original source checkpoints.

## Wheel (`investment_stack-0.1.0-py3-none-any.whl`)

Allowed files are exactly:

- `investment_stack/**/*.py` from `runtime/investment_stack/`.
- The five wheel metadata files: `METADATA`, `WHEEL`, `entry_points.txt`, `top_level.txt`, and `RECORD` under `investment_stack-0.1.0.dist-info/`.
- Exactly `config/freshness.yaml`, `config/materiality.yaml`, `config/providers.yaml`, `config/reconciliation.yaml`, and `config/web_research.yaml` under `investment_stack-0.1.0.data/data/`.
- For each of the eight names below, exactly `SKILL.md` and `agents/openai.yaml` under both `skills/<name>/` and `.agents/skills/<name>/`, installed as wheel data files under `investment_stack-0.1.0.data/data/`.

## Source distribution (`investment_stack-0.1.0.tar.gz`)

Allowed project files are exactly:

- `ARCHITECTURE.md`, `README.md`, `pyproject.toml`, `setup.py`, generated `setup.cfg`, and `MANIFEST.in`.
- `docs/workflow/deployment-allowlist.md` and `scripts/sync_agent_skills.py`.
- The five explicitly named `config/*.yaml` inputs above.
- All `runtime/investment_stack/**/*.py` source files and setuptools' six generated `runtime/investment_stack.egg-info/` metadata files (`PKG-INFO`, `SOURCES.txt`, `dependency_links.txt`, `entry_points.txt`, `requires.txt`, `top_level.txt`).
- For each of the eight skill names below, exactly `SKILL.md` and `agents/openai.yaml` under both `skills/<name>/` and `.agents/skills/<name>/`.

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
| Personal database schema | `3` | Latest personal migration number. |
| Run database schema | `2` | Latest run-evidence migration number. |
| Config files | per-file | YAML files carry their own `version`; `RunContext.config_version` is context metadata, not a distribution version. |

No release mapping between architecture `v1.3`, the `v1.3.1` hardening description in README, and Python distribution `0.1.0` is defined. This package task does not create a release, change migration history, or claim that a schema/config version was upgraded.
