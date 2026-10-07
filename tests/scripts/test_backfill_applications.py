"""Backfill rows are built from known facts, with a safe fallback."""

from datetime import datetime, timezone

from scripts.backfill_applications import KNOWN_APPLIES, build_backfill_rows

UPDATED = datetime(2026, 10, 7, 9, 48, 1, tzinfo=timezone.utc)


def test_known_jobs_get_their_real_reason_and_times():
    rows = build_backfill_rows([(23, UPDATED), (25, UPDATED)])

    assert rows[23]["reason"] == "applied manually via inspect --click"
    assert rows[23]["artifacts_dir"] == "artifacts/inspect/23"
    assert rows[25]["applied_at"] == KNOWN_APPLIES[25]["applied_at"]
    for row in rows.values():
        assert row["outcome"] == "applied"
        assert row["dry_run"] is False
        # Same rule as ck_applications_applied_after_approval.
        assert row["applied_at"] >= row["approved_at"]


def test_unknown_job_falls_back_to_status_time():
    rows = build_backfill_rows([(99, UPDATED)])

    assert rows[99]["approved_at"] == rows[99]["applied_at"] == UPDATED
    assert rows[99]["reason"] == "backfilled from jobs.status"


def test_nothing_to_backfill():
    assert build_backfill_rows([]) == {}
