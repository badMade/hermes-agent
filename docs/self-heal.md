# Self-Healing CI

This repository uses a self-adapting CI repair and drift detection automation bot. The bot runs on a dynamically computed schedule, on manual dispatch, or upon CI failure on the default branch.

## Contract: `Change-Type=mechanical-repair`

Bot PRs labeled `self-heal` bypass TDD + refactor-separation gates by specifying `Change-Type: mechanical-repair` in the PR body.

## Setup & Behavior

- **Self-Scheduling:** The bot analyzes merged PR activity (PR frequency) to compute its own run cadence.
- **Override:** You can manually edit the schedule in `.github/self-heal-schedule.yml`. If modified manually, the schedule is treated as an override.
- **Marker:** The `.github/self-heal-schedule.yml` file contains an exact `# AUTO-UPDATED` marker on the schedule line, which must be preserved during mutation.

## Permissions

The self-healing workflows require the following GitHub API permissions:
- `contents: write`
- `pull-requests: write`
- `actions: read`

## Reviewer Checklist

When reviewing a self-heal PR:
- Verify the step-by-step logs provided in the PR artifacts.
- Ensure the PR only touches approved domains (source, snapshots, lockfiles, deps config).
- Verify no secrets or credentials were inadvertently generated.
- Ensure the PR title is prefixed appropriately and the change-type contract is preserved.
