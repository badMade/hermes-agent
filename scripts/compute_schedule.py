#!/usr/bin/env python3
import subprocess
import json
import math
import re
import datetime
from typing import Tuple, List, Dict, Any

try:
    from ruamel.yaml import YAML  # type: ignore
except ImportError:
    YAML = None

def get_telemetry() -> Tuple[int, float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    pr_cmd = ["gh", "pr", "list", "--state", "merged", "--limit", "100", "--json", "mergedAt,title"]
    pr_result = subprocess.run(pr_cmd, capture_output=True, text=True)
    try:
        prs = json.loads(pr_result.stdout)
        num_prs = len(prs)
    except Exception:
        prs = []
        num_prs = 10

    ci_cmd = ["gh", "run", "list", "--workflow", "ci", "--limit", "100", "--json", "conclusion,headBranch"]
    ci_result = subprocess.run(ci_cmd, capture_output=True, text=True)
    try:
        runs = json.loads(ci_result.stdout)
        failures = sum(1 for r in runs if isinstance(r, dict) and r.get("conclusion") == "failure")
        num_runs = len(runs)
        failure_rate = failures / num_runs if num_runs > 0 else 0.0
    except Exception:
        runs = []
        failure_rate = 0.1

    return num_prs, failure_rate, prs, runs

def analyze_active_period(prs: List[Dict[str, Any]]) -> str:
    if not prs: return "2"
    hour_counts = {h: 0 for h in range(24)}
    for pr in prs:
        if isinstance(pr, dict) and "mergedAt" in pr:
            try:
                hour = int(pr["mergedAt"].split("T")[1][:2])
                hour_counts[hour] += 1
            except Exception: pass
    min_count = float('inf')
    quietest_start = 2
    for start in range(24):
        count = sum(hour_counts[(start + offset) % 24] for offset in range(4))
        if count < min_count:
            min_count = count
            quietest_start = start
    return str(quietest_start)

def update_schedule_file(schedule_expr: str) -> None:
    schedule_file = ".github/self-heal-schedule.yml"
    if YAML:
        yaml = YAML()
        yaml.preserve_quotes = True
        try:
            with open(schedule_file, "r", encoding="utf-8") as f:
                data = yaml.load(f)
        except Exception:
            data = {"schedule": "0 2 * * *"}

        # Check oscillation guard:
        try:
            last_updated = data.get("last_updated")
            if last_updated:
                lu_date = datetime.datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                if (datetime.datetime.now(datetime.timezone.utc) - lu_date).days < 1:
                    print("Oscillation guard: Schedule updated recently. Skipping.")
                    return
        except Exception:
            pass

        if isinstance(data, dict) and data.get("schedule") == schedule_expr: return
        if not isinstance(data, dict): data = {}
        data["schedule"] = schedule_expr
        data["rationale"] = "# AUTO-UPDATED"
        data["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(schedule_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
    else:
        try:
            with open(schedule_file, "r", encoding="utf-8") as f:
                content = f.read()
            if schedule_expr in content: return
        except Exception: pass
        content = f"""# AUTO-UPDATED\nschedule: "{schedule_expr}"\n"""
        with open(schedule_file, "w", encoding="utf-8") as f:
            f.write(content)

    # Also update the workflow file where the cron actually lives
    workflow_file = ".github/workflows/self-heal.yml"
    try:
        with open(workflow_file, "r", encoding="utf-8") as f:
            wf_content = f.read()

        wf_content = re.sub(r'# AUTO-UPDATED\n\s+- cron: ".*?"', f'# AUTO-UPDATED\n    - cron: "{schedule_expr}"', wf_content)

        with open(workflow_file, "w", encoding="utf-8") as f:
            f.write(wf_content)
    except Exception as e:
        print(f"Failed to update workflow cron: {e}")

def check_adjustment_triggers(prs: List[Dict[str, Any]], runs: List[Dict[str, Any]]) -> int:
    self_heal_successes = 0
    for pr in prs[:10]:
        if isinstance(pr, dict) and "Self-Heal" in pr.get("title", ""):
            self_heal_successes += 1
            if self_heal_successes >= 3: return 1
        elif self_heal_successes > 0: break

    empty_runs = 0
    for run in runs[:10]:
        if isinstance(run, dict) and run.get("headBranch", "").startswith("selfheal-") and run.get("conclusion") == "success":
            empty_runs += 1
            if empty_runs >= 3: return -1
        else:
            empty_runs = 0

    return 0

def compute_schedule() -> None:
    num_prs, failure_rate, prs, runs = get_telemetry()

    quiet_hour = analyze_active_period(prs)
    adjustment = check_adjustment_triggers(prs, runs)

    tier_val = 2
    if num_prs > 50 or failure_rate > 0.2: tier_val = 4
    elif num_prs > 20 or failure_rate > 0.1: tier_val = 3
    elif num_prs > 0: tier_val = 1
    else: tier_val = 0
    tier_val = max(0, min(4, tier_val + adjustment))

    if tier_val == 4: schedule_expr = "0 * * * *"
    elif tier_val == 3: schedule_expr = "0 */4 * * *"
    elif tier_val == 2: schedule_expr = f"0 {quiet_hour} * * *"
    elif tier_val == 1: schedule_expr = f"0 {quiet_hour} * * 0"
    else: schedule_expr = "0 0 1 * *"

    update_schedule_file(schedule_expr)

if __name__ == "__main__":
    compute_schedule()
