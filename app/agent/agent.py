import asyncio

import structlog
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    create_sdk_mcp_server,
)

from app.agent.approval import request_approval
from app.agent.claude_tools import (
    create_search_jobs_tool,
    create_get_job_details_tool,
)
from app.agent.context import AgentContext
from app.agent.state import AgentState
from app.config import settings
from app.logging_config import setup_logging
from app.services.profile_loader import load_profile

logger = structlog.get_logger(__name__)


async def run_agent():
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    candidate = load_profile(settings.PROFILE_PATH)

    logger.info(
        "profile_loaded",
        name=candidate.name,
        skills=len(candidate.skills),
    )

    state = AgentState(
        candidate=candidate
    )

    context = AgentContext(
        state=state
    )

    search_jobs = create_search_jobs_tool(
        context
    )

    get_job_details = create_get_job_details_tool(
        context
    )

    server = create_sdk_mcp_server(
        name="job_tools",
        version="1.0.0",
        tools=[
            search_jobs,
            get_job_details,
        ],
    )

    async for message in query(
        prompt=(
            "You are a job search agent.\n\n"
            "First, use search_jobs to search for "
            f"'{settings.JOB_SEARCH_KEYWORD}' in '{settings.JOB_SEARCH_LOCATION}'.\n\n"
            "After receiving the search results, "
            "use get_job_details for job 1.\n\n"
            "Then summarize the job details."
        ),
        options=ClaudeAgentOptions(
            mcp_servers={
                "job_tools": server
            },
            allowed_tools=[
                "mcp__job_tools__search_jobs",
                "mcp__job_tools__get_job_details",
            ],
        ),
    ):

        logger.debug(
            "agent_message_received",
            message=message
        )

    if state.current_job is None:

        logger.info("job_not_selected")

        return

    print("\n===== CURRENT JOB =====")

    print(
        f"Job: {state.current_job.title}"
    )

    print(
        f"Company: {state.current_job.company}"
    )

    state = request_approval(
        state=state,
        job_title=state.current_job.title,
        company=state.current_job.company
    )

    if state.approval_status == "approved":

        print(
            f"\nUser approved. "
            f"Next action: {state.next_action}"
        )

    else:

        print(
            f"\nUser rejected. "
            f"Next action: {state.next_action}"
        )


if __name__ == "__main__":
    asyncio.run(run_agent())