"""scripts/backfill_details: --dry-run lists jobs and never starts a workflow."""

import asyncio

from scripts import backfill_details


def test_dry_run_lists_and_starts_nothing(monkeypatch, capsys):
    async def load_candidates(limit):
        assert limit == 2
        return [(5, "discovered", "Python Developer"), (9, "expired", "Backend Engineer")]

    async def connect_client():
        raise AssertionError("dry run must not talk to Temporal")

    monkeypatch.setattr(backfill_details, "load_candidates", load_candidates)
    monkeypatch.setattr(backfill_details, "connect_client", connect_client)

    asyncio.run(backfill_details.main(limit=2, dry_run=True))

    out = capsys.readouterr().out
    assert "job     5  discovered" in out
    assert "2 job(s) would be fetched" in out


def test_nothing_to_do_starts_nothing(monkeypatch, capsys):
    async def load_candidates(limit):
        return []

    async def connect_client():
        raise AssertionError("nothing to backfill")

    monkeypatch.setattr(backfill_details, "load_candidates", load_candidates)
    monkeypatch.setattr(backfill_details, "connect_client", connect_client)

    asyncio.run(backfill_details.main(limit=10, dry_run=False))

    assert "Nothing to backfill" in capsys.readouterr().out
