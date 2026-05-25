#!/usr/bin/env bash
# Gates check: tests code quality and exits 0/1, silent unless error.

set -e

exec 3>&1
log_file=$(mktemp)

cleanup() {
    rm -f "$log_file"
}
trap cleanup EXIT

run_check() {
    local cmd="$1"
    if ! eval "$cmd" > "$log_file" 2>&1; then
        echo "Healthcheck failed on command: $cmd" >&3
        cat "$log_file" >&3
        exit 1
    fi
}

run_check "uv run ruff check ." || { exit 1; }
run_check "uv run ruff format --check ." || { exit 1; }
run_check "uv run mypy --strict ." || { exit 1; }
run_check "uv run scripts/run_tests.sh" || { exit 1; }
run_check "uv build" || { exit 1; }

exit 0
