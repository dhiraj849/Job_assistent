# Retired histories

Recorded before a patch whose old branch has since been removed, or with a
`patched()` marker (deprecated=false) for a patch whose call has since been
removed. Today's code can no longer replay them, by design: no open workflow
was in this state when the code changed (checked by replaying every open run).
Kept only so `test_retired_histories_no_longer_replay` proves that.

Step 1 (`deprecate_patch`):

- `apply_dry_run_v0.json` — before `apply-job-v1` and `record-approval-v1`
  (ran `update_job_status(APPROVED)` + `apply_job_dry_run`).
- `apply_job_v1.json` — before `record-approval-v1`
  (ran `update_job_status(APPROVED)` + `apply_job`).

Step 2 (calls removed; these had non-deprecated markers for both patches):

- `record_approval_v1.json` — real job-38 history. No replacement needed:
  `deprecated_markers_v1.json` covers the same approve + apply path.
- `ready_for_you_v1.json` — replaced by `ready_for_you_v2.json`.
- `cap_expired_v1.json` — also the only history from before
  `cap-expiry-outcome-v1`; replaced by `cap_expired_v2.json` (new path only).
