#!/usr/bin/env python3
"""
Self-healing repair pipeline.

Executes 6 idempotent steps to repair the codebase:
1. Rebuild/reinstall toolchain + dependencies
2. Lint + format auto-fix
3. Snapshot / generated-test updates
4. Type stubs + analyzer config
5. Dependency re-resolution / lockfile refresh
6. Static asset regeneration
"""

import subprocess
import sys


def log_step(n: int, name: str, status: str) -> None:
    """Log the start or result of a pipeline step.

    Args:
        n: Step number.
        name: Step name or result description.
        status: The status ("starting", "succeeded with fix", "no-op", "failed: <reason>").
    """
    if status == "starting":
        print(f"step {n}/6 {name} starting")
    else:
        print(f"step {n} {status}")


def check_health_and_diff(step_num: int) -> bool:
    """Run the healthcheck and check for a non-empty diff.

    Args:
        step_num: The current step number for logging.

    Returns:
        True if the pipeline should exit with success, False to continue.
    """
    hc_result = subprocess.run(
        ["python3", "scripts/healthcheck.py"], capture_output=True
    )
    hc_passed = hc_result.returncode == 0

    diff_result = subprocess.run(["git", "diff", "--quiet"], capture_output=True)
    has_diff = diff_result.returncode != 0

    if hc_passed and has_diff:
        log_step(step_num, "", "succeeded with fix")
        return True
    if hc_passed and not has_diff:
        log_step(step_num, "", "no-op")
        return False

    # If healthcheck failed, log and continue
    reason = "healthcheck failed" if not hc_passed else "unknown failure"
    log_step(step_num, "", f"failed: {reason}")
    return False


def run_cmd(cmd: list[str]) -> bool:
    """Run a command and return True if successful.

    Args:
        cmd: Command list to execute.

    Returns:
        bool: True if the command exits with 0.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def step_1_toolchain() -> None:
    """Step 1: Rebuild/reinstall toolchain + dependencies."""
    run_cmd(["uv", "sync"])
    # Also support poetry/pip if applicable, but repo seems to use uv and pip-tools


def step_2_lint() -> None:
    """Step 2: Lint + format auto-fix."""
    run_cmd(["ruff", "check", "--fix", "."])
    run_cmd(["ruff", "format", "."])


def step_3_snapshots() -> None:
    """Step 3: Snapshot / generated-test updates."""
    # Assuming pytest-snapshot is installed and configured
    run_cmd(["pytest", "--snapshot-update"])


def step_4_type_stubs() -> None:
    """Step 4: Type stubs + analyzer config."""
    # Run stubgen or similar if needed. For now, just re-run mypy to clear caches
    run_cmd(["mypy", "--install-types", "--non-interactive", "."])


def step_5_lockfile() -> None:
    """Step 5: Dependency re-resolution / lockfile refresh."""
    # Refresh lockfiles based on the tools found
    run_cmd(["uv", "lock"])


def step_6_static_assets() -> None:
    """Step 6: Static asset regeneration."""
    pass  # No default static asset generators detected


def main() -> None:
    """Run the 6-step self-healing pipeline."""
    steps = [
        (1, "toolchain", step_1_toolchain),
        (2, "lint", step_2_lint),
        (3, "snapshots", step_3_snapshots),
        (4, "type stubs", step_4_type_stubs),
        (5, "lockfile", step_5_lockfile),
        (6, "static assets", step_6_static_assets),
    ]

    for step_num, name, func in steps:
        log_step(step_num, name, "starting")
        try:
            func()
        except Exception as e:
            log_step(step_num, "", f"failed: Exception {e}")
            continue

        if check_health_and_diff(step_num):
            sys.exit(0)

    print("no fix found across all steps")
    sys.exit(1)


if __name__ == "__main__":
    main()
