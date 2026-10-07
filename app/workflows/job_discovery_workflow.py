from datetime import timedelta

from temporalio import workflow

from app.workflows.job_application_workflow import JobApplicationWorkflow
from app.workflows.retry import RETRY_POLICY

# Activities import browser/DB libraries. Passing them through keeps the
# workflow sandbox from re-importing them (they are never called here directly).
with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import discover_jobs, save_jobs


@workflow.defn
class JobDiscoveryWorkflow:

    @workflow.run
    async def run(self, keyword: str, location: str) -> dict:
        jobs = await workflow.execute_activity(
            discover_jobs,
            args=[keyword, location],
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RETRY_POLICY,
        )

        # Nothing scraped: skip the DB round trip.
        if not jobs:
            return {"found": 0, "new": 0}

        new_ids = await workflow.execute_activity(
            save_jobs,
            jobs,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_POLICY,
        )

        # One application workflow per new job. ABANDON lets discovery finish
        # while the children keep waiting (up to days) for approval.
        for job_id in new_ids:
            await workflow.start_child_workflow(
                JobApplicationWorkflow.run,
                job_id,
                id=f"job-{job_id}",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )

        return {"found": len(jobs), "new": len(new_ids)}
