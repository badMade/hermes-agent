#!/usr/bin/env python3
"""
Compute Self-Heal Schedule

Computes a new schedule based on basic telemetry and safely updates
the .github/self-heal-schedule.yml using ruamel.yaml if available, or marker-based replacement.
"""

import os
import subprocess
import re
import sys

SCHEDULE_FILE = ".github/self-heal-schedule.yml"
MARKER = "# AUTO-UPDATED"

def compute_new_schedule() -> str:
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "15"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 10:
                print("High churn detected. Setting daily schedule.")
                return "0 2 * * *"
    except FileNotFoundError:
        pass

    print("Standard churn detected. Setting weekly schedule.")
    return "0 2 * * 0"

def update_schedule_file(new_cron: str) -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(repo_root, SCHEDULE_FILE)

    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        sys.exit(1)

    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)

        if data["schedule"]["cron"] == new_cron:
            print("Schedule unchanged.")
            sys.exit(0)

        data["schedule"]["cron"] = new_cron
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        print(f"Updated {SCHEDULE_FILE} with new schedule: {new_cron} using ruamel.yaml")
        return
    except Exception:
        pass

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

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

    print(f"Updated {SCHEDULE_FILE} with new schedule: {new_cron} using regex fallback")

def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    new_cron = compute_new_schedule()
    update_schedule_file(new_cron)

if __name__ == "__main__":
    main()
