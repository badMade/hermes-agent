# Self-Heal Auto Repair Setup

This document describes the self-adapting CI repair and drift detection automation for `hermes-agent`.

## Purpose
Automates common maintenance tasks such as format fixing, linting, lockfile updating, and typing checks.

## Architecture
- `scripts/healthcheck.sh`
- `scripts/self_heal.sh`
- `scripts/compute_schedule.py`
- `.github/workflows/self-heal.yml`
- `.github/workflows/compute-schedule.yml`
- `.github/self-heal-schedule.yml`

## Triggers
1. **Scheduled**: Telemetry derived, updating the frequency based on churn.
2. **Manual Dispatch**: Ability to trigger on demand.
3. **CI Failure**: Runs when the `ci` workflow fails.

## Self-Scheduling logic
The `compute_schedule.py` script queries the Github API to determine PR merge frequencies and CI failure rates to compute an appropriate execution tier (e.g. High, Active, Standard, Low-churn, Dormant).

## Overriding the Schedule
To manually override, edit `.github/self-heal-schedule.yml`. Change the `schedule:` cron value.

## Reviewer Checklist
- [ ] No secrets exposed.
- [ ] `selfheal-*` PR branches created.
- [ ] Verified diff output correctly fixes drift.
- [ ] Ensure idempotency in healthcheck/self_heal runs.
