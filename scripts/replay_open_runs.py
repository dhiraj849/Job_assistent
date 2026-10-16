"""Replay every open JobApplicationWorkflow with the code in this checkout.

Run it before (and once after) deploying a workflow change, e.g. removing a
patch: a run that fails here would get stuck with a non-determinism error on
the new worker. Read-only: it only downloads histories.

Usage: uv run python -m scripts.replay_open_runs
Exit code 1 if any run fails to replay.
"""

import asyncio
import json
import sys

from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from app.workflows.client import connect_client
from app.workflows.job_application_workflow import JobApplicationWorkflow

QUERY = "WorkflowType='JobApplicationWorkflow' AND ExecutionStatus='Running'"


def patch_markers(history: WorkflowHistory) -> dict[str, bool]:
    """Patch id -> "deprecated" flag. A deprecated=false marker blocks removing that patch."""
    markers = {}
    for event in history.events:
        if event.HasField("marker_recorded_event_attributes"):
            for payloads in event.marker_recorded_event_attributes.details.values():
                for payload in payloads.payloads:
                    data = json.loads(payload.data)
                    markers[data["id"]] = data["deprecated"]
    return markers


async def main() -> int:
    client = await connect_client()
    replayer = Replayer(
        workflows=[JobApplicationWorkflow], data_converter=pydantic_data_converter
    )
    runs = [w async for w in client.list_workflows(QUERY)]
    print(f"Open runs: {len(runs)}")

    failed = 0
    for run in runs:
        history = await client.get_workflow_handle(run.id, run_id=run.run_id).fetch_history()
        try:
            await replayer.replay_workflow(history)
            result = "OK"
        except Exception as error:  # any replay failure blocks the deploy
            failed += 1
            result = f"FAIL {type(error).__name__}: {str(error)[:200]}"
        print(f"{run.id:<12} started {run.start_time:%Y-%m-%d}  markers={patch_markers(history)}  {result}")

    print("All open runs replay." if not failed else f"{failed} run(s) failed: do not deploy.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
