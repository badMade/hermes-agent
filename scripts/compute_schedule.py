#!/usr/bin/env python3
"""
Compute telemetry-derived schedule for self-healing CI.
Updates .github/self-heal-schedule.yml while preserving `# AUTO-UPDATED` marker.
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def run_gh_cmd(cmd: list[str]) -> str:
    """Run a gh CLI command and return its output.

    Args:
        cmd: List of string arguments starting with 'gh'.

    Returns:
        The command output as a string.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running gh command {cmd}: {e.stderr}")
        return ""
    except FileNotFoundError:
        print("gh CLI not found")
        return ""


def get_pr_frequency() -> int:
    """Get the number of PRs merged recently."""
    out = run_gh_cmd([
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        "100",
        "--json",
        "number",
    ])
    if not out:
        return 0
    try:
        prs = json.loads(out)
        return len(prs)
    except json.JSONDecodeError:
        return 0


def get_ci_failure_rate() -> float:
    """Get the recent CI failure rate."""
    out = run_gh_cmd([
        "gh",
        "run",
        "list",
        "--workflow=ci",
        "--limit",
        "100",
        "--json",
        "conclusion",
    ])
    if not out:
        return 0.0
    try:
        runs = json.loads(out)
        if not runs:
            return 0.0
        failures = sum(1 for r in runs if r.get("conclusion") == "failure")
        return failures / len(runs)
    except json.JSONDecodeError:
        return 0.0


def get_commit_distribution() -> float:
    """Get a metric representing commit distribution."""
    out = run_gh_cmd(["git", "log", "--since=7.days", "--format=%H"])
    if not out:
        return 0.0
    return len(out.splitlines()) / 7.0


def determine_tier(pr_count: int, failure_rate: float, commits_per_day: float) -> str:
    """Determine schedule tier based on PR activity.

    Args:
        pr_count: The number of PRs merged recently.

    Returns:
        The cron schedule expression.
    """
    score = pr_count + (failure_rate * 100) + commits_per_day
    if score > 50:
        return "0 * * * *"  # high - hourly
    elif score > 20:
        return "0 */4 * * *"  # active - every 4 hours
    elif score > 5:
        return "0 0 * * *"  # standard - daily
    elif score > 0:
        return "0 0 * * 0"  # low-churn - weekly
    else:
        return "0 0 1 * *"  # dormant - monthly


def update_schedule_file(new_schedule: str) -> None:
    """Update the schedule files preserving the marker."""
    for filename in [
        ".github/self-heal-schedule.yml",
        ".github/workflows/self-heal.yml",
    ]:
        file_path = Path(filename)
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        updated_lines = []

        for line in lines:
            if "schedule:" in line and "AUTO-UPDATED" in line:
                if ".github/self-heal-schedule.yml" in filename:
                    updated_lines.append(f'schedule: "{new_schedule}"   # AUTO-UPDATED')
                else:
                    updated_lines.append(f"    - cron: '{new_schedule}' # AUTO-UPDATED")
            elif "- cron:" in line and "AUTO-UPDATED" in line:
                updated_lines.append(f"    - cron: '{new_schedule}' # AUTO-UPDATED")
            else:
                updated_lines.append(line)

        file_path.write_text(chr(10).join(updated_lines) + chr(10), encoding="utf-8")


def main() -> None:
    """Compute and update the schedule."""
    # Check if there are open schedule PRs
    open_prs_out = run_gh_cmd([
        "gh",
        "pr",
        "list",
        "--label",
        "self-heal-schedule",
        "--state",
        "open",
        "--json",
        "number",
    ])
    if open_prs_out:
        try:
            open_prs = json.loads(open_prs_out)
            if open_prs:
                print("Open schedule PRs exist. Skipping update.")
                sys.exit(0)
        except json.JSONDecodeError:
            pass

    pr_count = get_pr_frequency()
    failure_rate = get_ci_failure_rate()
    commits_per_day = get_commit_distribution()
    new_schedule = determine_tier(pr_count, failure_rate, commits_per_day)
    print(f"Computed new schedule: {new_schedule}")

    update_schedule_file(new_schedule)


if __name__ == "__main__":
    main()
