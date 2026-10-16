from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

from app.workflows.job_application_workflow import DETAILS_DEADLINE, DETAILS_TIMEOUT
from app.workflows.retry import RETRY_POLICY
from app.workflows.task_queues import BROWSER_TASK_QUEUE

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import embed_job, fetch_job_details


@workflow.defn
class BackfillDetailsWorkflow:
    """Read the detail page of jobs saved before detail fetching existed,
    then re-embed each one so Qdrant matches the DB.

    No filter, LLM match or approval: old jobs keep their status. Jobs are
    done one at a time; the browser queue and fetch_job_details' own delay
    space out the Naukri requests.
    """

    @workflow.run
    async def run(self, job_ids: list[int]) -> dict:
        fetched: list[int] = []
        failed: list[int] = []

        for job_id in job_ids:
            try:
                await workflow.execute_activity(
                    fetch_job_details,
                    job_id,
                    task_queue=BROWSER_TASK_QUEUE,
                    start_to_close_timeout=DETAILS_TIMEOUT,
                    schedule_to_close_timeout=DETAILS_DEADLINE,
                    retry_policy=RETRY_POLICY,
                )
            except ActivityError as error:
                # An old posting may be gone or unparseable: note it and go on.
                # It keeps details NULL, so the next backfill tries it again.
                workflow.logger.warning("job %s: details not fetched (%s)", job_id, error.cause)
                failed.append(job_id)
                continue

            # Right after the fetch, so a run stopped halfway never leaves a
            # job with a full JD in the DB but a snippet vector in Qdrant.
            await workflow.execute_activity(
                embed_job,
                job_id,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RETRY_POLICY,
            )
            fetched.append(job_id)

        return {"fetched": fetched, "failed": failed}
