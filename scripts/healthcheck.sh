#!/usr/bin/env bash
# Healthcheck for Self-Heal Pipeline
# Silent unless there is an error.
# Checks lockfiles, formatting, linting, type checks, and tests.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

failed=0

# Lockfile check
if ! uv lock --check > /dev/null 2>&1; then
    echo "Healthcheck failed: uv lock out of date"
    uv lock --check
    failed=1
fi

# Format check
if [ $failed -eq 0 ] && ! uv run ruff format --check . > /dev/null 2>&1; then
    echo "Healthcheck failed: ruff format"
    uv run ruff format --check .
    failed=1
fi

# Lint check
if [ $failed -eq 0 ] && ! uv run ruff check . > /dev/null 2>&1; then
    echo "Healthcheck failed: ruff check"
    uv run ruff check .
    failed=1
fi

# Type check
if [ $failed -eq 0 ] && ! uv run ty check > /dev/null 2>&1; then
    echo "Healthcheck failed: ty check"
    uv run ty check
    failed=1
fi

# Test check
if [ $failed -eq 0 ]; then
    # Create temp file for test output to keep silent unless failing
    tmp_out=$(mktemp)
    if ! scripts/run_tests.sh > "$tmp_out" 2>&1; then
        echo "Healthcheck failed: tests"
        cat "$tmp_out"
        failed=1
    fi
    rm -f "$tmp_out"
fi

if [ $failed -ne 0 ]; then
    exit 1
fi

exit 0