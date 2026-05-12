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


def determine_tier(pr_count: int) -> str:
    """Determine schedule tier based on PR activity.

    Args:
        pr_count: The number of PRs merged recently.

    Returns:
        The cron schedule expression.
    """
    if pr_count > 50:
        return "0 * * * *"  # high - hourly
    elif pr_count > 20:
        return "0 */4 * * *"  # active - every 4 hours
    elif pr_count > 5:
        return "0 0 * * *"  # standard - daily
    elif pr_count > 0:
        return "0 0 * * 0"  # low-churn - weekly
    else:
        return "0 0 1 * *"  # dormant - monthly


def update_schedule_file(new_schedule: str) -> None:
    """Update the schedule file preserving the marker.

    Args:
        new_schedule: The new cron expression.
    """
    file_path = Path(".github/self-heal-schedule.yml")
    if not file_path.exists():
        # Create it if it doesn't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = f'schedule: "{new_schedule}"   # AUTO-UPDATED\n'
        file_path.write_text(content, encoding="utf-8")
        return

    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    updated_lines = []

    for line in lines:
        if "schedule:" in line and "# AUTO-UPDATED" in line:
            # Replace the schedule expression but keep the marker
            updated_lines.append(f'schedule: "{new_schedule}"   # AUTO-UPDATED')
        else:
            updated_lines.append(line)

    file_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


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
    new_schedule = determine_tier(pr_count)
    print(f"Computed new schedule based on {pr_count} PRs: {new_schedule}")

    update_schedule_file(new_schedule)


if __name__ == "__main__":
    main()
