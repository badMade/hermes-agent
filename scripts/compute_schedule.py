#!/usr/bin/env python3
"""
Compute Self-Heal Schedule

Computes a new schedule based on PR telemetry and safely updates
the .github/self-heal-schedule.yml. Tries ruamel.yaml for a safe
round-trip and falls back to marker-based regex.
"""

import os
import subprocess
import re
import sys
import datetime

SCHEDULE_FILE = ".github/self-heal-schedule.yml"
MARKER = "# AUTO-UPDATED"

def compute_new_schedule() -> str:
    """
    Computes new schedule cron string based on PR merge frequency telemetry.
    Cadence tiers:
    - High churn (>15 PRs/week): daily at 01:00 -> "0 1 * * *"
    - Active (10-15 PRs/week): Mon/Wed/Fri at 01:00 -> "0 1 * * 1,3,5"
    - Standard (5-9 PRs/week): Tue/Thu at 01:00 -> "0 1 * * 2,4"
    - Low-churn (1-4 PRs/week): Weekly on Sun at 01:00 -> "0 1 * * 0"
    - Dormant (0 PRs/week): Monthly on 1st at 01:00 -> "0 1 1 * *"
    """
    try:
        # Calculate the date 7 days ago
        seven_days_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')

        # Check if gh CLI is available and query merged PRs in the last week
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--search", f"merged:>={seven_days_ago}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
            pr_count = len(lines)

            if pr_count > 15:
                print(f"High churn detected ({pr_count} PRs). Setting daily schedule.")
                return "0 1 * * *"
            elif pr_count >= 10:
                print(f"Active churn detected ({pr_count} PRs). Setting Mon/Wed/Fri schedule.")
                return "0 1 * * 1,3,5"
            elif pr_count >= 5:
                print(f"Standard churn detected ({pr_count} PRs). Setting Tue/Thu schedule.")
                return "0 1 * * 2,4"
            elif pr_count >= 1:
                print(f"Low-churn detected ({pr_count} PRs). Setting Weekly schedule.")
                return "0 1 * * 0"
            else:
                print(f"Dormant detected ({pr_count} PRs). Setting Monthly schedule.")
                return "0 1 1 * *"
    except FileNotFoundError:
        print("gh CLI not found, defaulting to Standard schedule.")
        pass

    # Default if gh fails
    print("Defaulting to Standard schedule.")
    return "0 1 * * 2,4"

def update_schedule_file(new_cron: str) -> None:
    """Safely updates the schedule file using ruamel.yaml or marker replacement."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(repo_root, SCHEDULE_FILE)

    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Try ruamel.yaml first
    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True

        # Load yaml content
        data = yaml.load(content)

        if data.get('schedule', {}).get('cron') == new_cron:
            print("Schedule unchanged.")
            sys.exit(0)

        data['schedule']['cron'] = new_cron

        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        print(f"Updated {SCHEDULE_FILE} via ruamel.yaml with new schedule: {new_cron}")
        return

    except ImportError:
        print("ruamel.yaml not available, falling back to regex replacement.")

    # Fallback to Regex Replacement
    if MARKER not in content:
        print(f"Marker '{MARKER}' not found in {file_path}.")
        sys.exit(1)

    new_content = re.sub(
        r'cron:\s*".*?"',
        f'cron: "{new_cron}"',
        content
    )

    if new_content == content:
        print("Schedule unchanged.")
        sys.exit(0)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Updated {SCHEDULE_FILE} via regex with new schedule: {new_cron}")

def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    new_cron = compute_new_schedule()
    update_schedule_file(new_cron)

if __name__ == "__main__":
    main()
