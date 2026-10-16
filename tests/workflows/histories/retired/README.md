# Retired histories

Recorded before a patch whose old branch has since been removed
(`deprecate_patch`, step 1 of 2). Today's code can no longer replay them, by
design: no open workflow was in this state when the branch was removed.
Kept only so `test_retired_histories_no_longer_replay` proves that.

- `apply_dry_run_v0.json` — before `apply-job-v1` and `record-approval-v1`
  (ran `update_job_status(APPROVED)` + `apply_job_dry_run`).
- `apply_job_v1.json` — before `record-approval-v1`
  (ran `update_job_status(APPROVED)` + `apply_job`).
