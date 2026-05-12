# ADR 0001: Add `selfheal` Dependency Group

## Context

We are introducing self-adapting CI repair and drift detection automation. To accomplish this safely and deterministically, the automation requires a small set of dependencies to execute tasks like code formatting, linting, type checking, test execution, and safe YAML manipulation.

## Decision

We will add a new dependency group named `selfheal` in `pyproject.toml` (PEP 735). This group will exclusively contain the tools required for the self-healing steps.

## Alternatives Considered

- **Global/Dev Installation:** Adding these tools to the main `dev` dependencies. We rejected this because the self-healing bot needs isolation, and some dependencies (like safe YAML roundtripping via `ruamel.yaml` or `detect-secrets`) might not be universally needed by all contributors.
- **Dynamic Installation:** `pip install`ing tools on the fly in the CI runner. We rejected this to limit supply chain attack surface and ensure deterministic tool versions by locking them in the project manifest.

## Justification Table

| Dependency | Step Served | Supply-Chain Notes |
| :--- | :--- | :--- |
| `ruff` | Step 2 (Lint + format auto-fix) | Pinned core linter. |
| `mypy` | Healthcheck Gate | Pinned core type checker. |
| `pytest` | Healthcheck Gate | Pinned core test runner. |
| `pytest-snapshot` | Step 3 (Snapshot regen) | Only used if snapshot fixtures are present. |
| `pip-tools` | Step 5 (Lockfile refresh) | Used to safely manage dependencies. |
| `ruamel.yaml` | Schedule mutation | Safe YAML round-trip editing (preserves comments). |
| `detect-secrets` | Gate (Diff scan) | Prevents committing high-entropy tokens or secrets. |

## Exit Plan

If the self-healing CI is decommissioned:
1. Uninstall the `selfheal` dependency group.
2. Delete the `[dependency-groups]` section for `selfheal` in `pyproject.toml`.
3. Delete `scripts/healthcheck.*`, `scripts/self_heal.*`, and `scripts/compute_schedule.*`.
4. Delete the workflows `.github/workflows/self-heal.yml` and `.github/workflows/compute-schedule.yml`.
5. Remove this ADR.
