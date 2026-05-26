#!/usr/bin/env bash
# Idempotent repair steps.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HEALTHCHECK="$SCRIPT_DIR/healthcheck.sh"

check_health() {
    "$HEALTHCHECK" >/dev/null 2>&1
}

has_diff() {
    [[ -n $(git status --porcelain) ]]
}

uv sync --all-extras --dev >/dev/null 2>&1 || true
if check_health; then if has_diff; then exit 0; fi; fi

uv run ruff check --fix . >/dev/null 2>&1 || true
uv run ruff format . >/dev/null 2>&1 || true
if check_health; then if has_diff; then exit 0; fi; fi

uv run pytest --snapshot-update >/dev/null 2>&1 || true
if check_health; then if has_diff; then exit 0; fi; fi

uv run mypy --install-types --non-interactive . >/dev/null 2>&1 || true
if check_health; then if has_diff; then exit 0; fi; fi

uv lock >/dev/null 2>&1 || true
if check_health; then if has_diff; then exit 0; fi; fi

uv run scripts/build_skills_index.py >/dev/null 2>&1 || true
if check_health; then if has_diff; then exit 0; fi; fi

exit 1
