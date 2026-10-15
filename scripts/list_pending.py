"""List everything waiting on me: approvals, and jobs that need a human.

Usage: uv run python -m scripts.list_pending
Then decide: uv run python -m scripts.decide_job <job_id> yes|no [note]
Company site ready: uv run python -m scripts.apply_company_site <job_id>
Fixed one by hand? uv run python -m scripts.mark_applied <job_id> --reason "..."
"""

import asyncio

from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository


async def main() -> None:
    async with SessionLocal() as session:
        repo = JobRepository(session)
        pending = await repo.get_pending_approvals()
        attention = await repo.get_jobs_needing_attention()
        ready = await repo.get_ready_for_you()
    await engine.dispose()

    print("== Awaiting approval")
    if not pending:
        print("No jobs awaiting approval.")
    else:
        print(f"{'ID':>6}  {'SCORE':>5}  {'LEVEL':<9}  TITLE @ COMPANY")
        for job_id, title, company, score, level in pending:
            print(f"{job_id:>6}  {score:>5}  {level:<9}  {title} @ {company}")

    print("\n== Ready for you (company site: I fill, you finish and submit)")
    if not ready:
        print("No company-site forms waiting.")
    else:
        # Grouped by what I will have to do on the page (a hint: an OTP can
        # also appear only after the email is typed).
        groups: dict[str, list] = {}
        for row in ready:
            steps = row[4].replace(",", " + ").upper() if row[4] else "no extra step seen"
            groups.setdefault(steps, []).append(row)
        for steps, rows in sorted(groups.items()):
            print(f"  -- {steps}")
            for job_id, title, company, portal, _, url in rows:
                print(f"{job_id:>6}  {portal:<14}  {title} @ {company}")
                print(f"{'':>8}{url}")
        print("  Run: uv run python -m scripts.apply_company_site <job_id>")

    print("\n== Needs attention (needs_manual / failed)")
    if not attention:
        print("Nothing needs attention.")
        return
    for job_id, title, company, status, reason, artifacts_dir in attention:
        print(f"{job_id:>6}  {status:<12}  {title} @ {company}")
        # No reason: the workflow failed before apply (no applications row).
        print(f"{'':>8}reason: {reason or '(none recorded, see Temporal UI)'}")
        if artifacts_dir:
            print(f"{'':>8}artifacts: {artifacts_dir}")


if __name__ == "__main__":
    asyncio.run(main())
