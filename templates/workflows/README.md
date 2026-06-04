# Workflow templates

Portable, parameterized copies of this repo's GitHub Actions workflows, meant to
be dropped into another repository and customized. These files live **outside**
`.github/workflows/` on purpose — placing a `.yml` there activates it, and you
don't want two auto-mergers competing in this repo.

## `auto-merge.yml`

A generic version of [`../../.github/workflows/auto-merge.yml`](../../.github/workflows/auto-merge.yml).
It squash-merges a PR once CI is green, a review happened, and a required label
is present. The full decision flow and design notes are in
[`../../AUTO_MERGE.md`](../../AUTO_MERGE.md).

### How to adopt it in another repo

1. **Copy** `auto-merge.yml` to `.github/workflows/auto-merge.yml` in the target
   repo.
2. **Edit the `on.workflow_run.workflows` list** — set it to the display `name:`
   of every CI workflow that must pass before merge. (This list cannot read env
   vars, so it's edited directly. Look for the `# 👈 EDIT` marker.)
3. **Edit the `env:` config block** on the `auto-merge` job:
   | Variable | Purpose |
   |----------|---------|
   | `REQUIRED_LABEL` | Label that must be present to merge (default `reviewed`). |
   | `AUTO_MERGE_JOB_NAME` | Keep in sync with the job's `name:` so its own check runs are excluded. |
   | `MERGE_METHOD` | `squash`, `merge`, or `rebase`. |
   | `REVIEW_BOTS` | Comma-separated bot logins whose activity counts as a review. |
   | `POLL_INTERVAL_MS` / `POLL_TIMEOUT_MS` | Poll cadence/limit for review/label/comment triggers. |
   | `SETTLE_DELAY_MS` | Delay before reading state on non-`workflow_run` events. |
4. **If you rename the job**, also update the
   `github.event.workflow_run.name != 'Auto-merge'` self-trigger guard in the
   job-level `if:`.
5. **Merge to the default branch.** `workflow_run` triggers are only active once
   the file is on the repo's default branch.

### Requirements in the target repo

- Create the `REQUIRED_LABEL` label (e.g. `reviewed`).
- The default `GITHUB_TOKEN` needs the `permissions:` already declared in the
  file. If your org sets "Read repository contents permission" as the default,
  the per-job `permissions:` block grants the rest.
- For the merge to succeed, repo settings must allow the chosen `MERGE_METHOD`
  (e.g. "Allow squash merging" enabled).
