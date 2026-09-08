# Self-Heal Coding Agent Pipeline

This repository uses an automated Self-Heal Pipeline designed to safely repair code drift, regenerate lockfiles, apply linters, and keep the repository healthy without human intervention.

## Triggers
1. **Scheduled:** Runs periodically (configured in `.github/self-heal-schedule.yml`).
2. **CI Failure:** Triggers on any failure of the main `ci` workflows.
3. **Manual Dispatch:** Can be run manually from the GitHub Actions UI.

## Components
- `.github/workflows/self-heal.yml`: Main workflow executing the repair.
- `.github/workflows/compute-schedule.yml`: Workflow that runs telemetry to update the self-heal schedule dynamically.
- `.github/self-heal-schedule.yml`: Holds the current schedule, auto-updated by telemetry logic.
- `scripts/healthcheck.sh`: Ensures tests/linters pass before and after applying fixes.
- `scripts/self_heal.py`: Idempotent script running various automated repairs (e.g. `uv lock`, `ruff check --fix`, etc.).
- `scripts/compute_schedule.py`: Logic calculating optimal schedule from repo metrics.

## Self-Scheduling
The schedule is derived based on telemetry like PR merge frequency and CI failure rates. To override this behavior manually, edit `.github/self-heal-schedule.yml` directly—though manual edits will be respected, changes to the rest of the file format outside the `cron` parameter might break the auto-updater. The `# AUTO-UPDATED` marker is essential for this round-trip safety.

## Reviewer Checklist for Self-Heal PRs
- [ ] Ensure only standard formatting or lockfile changes are present.
- [ ] Confirm tests pass and no functional logic was modified.
- [ ] Check if the changes indicate an underlying issue that needs to be permanently fixed in a development PR.
