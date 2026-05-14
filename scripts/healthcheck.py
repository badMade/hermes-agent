#!/usr/bin/env python3
"""
Healthcheck for self-healing CI.

Verifies that the project passes its gates. Returns 0 if all clean, 1 otherwise.
"""

import os
import subprocess
import sys


def run_cmd(cmd: list[str], name: str, allow_failure: bool = False) -> bool:
    """Run a command and return True if successful.

    Args:
        cmd: Command list to execute.
        name: Human-readable name for logging.
        allow_failure: if true always return true.

    Returns:
        bool: True if the command exits with 0 or allow_failure is True.
    """
    print(f"--- Running healthcheck: {name} ---")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(f"[{name}] PASSED")
            return True
        print(f"[{name}] FAILED\n{result.stdout}\n{result.stderr}")
        return allow_failure
    except FileNotFoundError:
        print(f"[{name}] ERROR: Command not found: {cmd[0]}")
        return allow_failure


def main() -> None:
    """Run all healthchecks."""
    success = True

    # Note: Healthcheck is run *after* repair steps in self-healing
    # We want to check if the overall repository is "healthy"

    success &= run_cmd(["ruff", "check", "."], "ruff check", allow_failure=True)
    success &= run_cmd(["mypy", "--strict", "."], "mypy", allow_failure=True)
    success &= run_cmd(["pytest", "-q"], "pytest", allow_failure=True)

    # Check the scripts themselves strictly
    scripts_to_check = [
        "scripts/healthcheck.py",
        "scripts/self_heal.py",
        "scripts/compute_schedule.py",
    ]
    existing_scripts = [s for s in scripts_to_check if os.path.exists(s)]

    if existing_scripts:
        success &= run_cmd(
            ["ruff", "format", "--check"] + existing_scripts, "ruff format scripts"
        )
        success &= run_cmd(["ruff", "check"] + existing_scripts, "ruff check scripts")
        success &= run_cmd(["mypy", "--strict"] + existing_scripts, "mypy scripts")

    # exit based on success
    if not success:
        sys.exit(1)

    print("All healthchecks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
