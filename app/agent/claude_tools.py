import structlog
from claude_agent_sdk import tool

from app.agent.context import AgentContext
from app.job_sources.naukri import NaukriJobSource

logger = structlog.get_logger(__name__)


def create_search_jobs_tool(context: AgentContext):

    @tool(
        "search_jobs",
        "Search for jobs using a keyword and location.",
        {
            "keyword": {
                "type": "string",
                "description": "Job search keyword"
            },
            "location": {
                "type": "string",
                "description": "Job search location"
            }
        }
    )
    async def search_jobs(args):

        keyword = args["keyword"]
        location = args["location"]

        logger.info(
            "job_search_started",
            keyword=keyword,
            location=location
        )

        # Create the existing Naukri job source.
        job_source = NaukriJobSource(
            keyword=keyword,
            location=location
        )

        # This internally uses Playwright.
        jobs = await job_source.get_jobs()

        # Store the real jobs in AgentState.
        context.state.jobs = jobs

        if not jobs:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"No jobs found for '{keyword}' "
                            f"in '{location}'."
                        )
                    }
                ]
            }

        job_lines = []

        for index, job in enumerate(jobs, start=1):
            job_lines.append(
                f"{index}. {job.title} | "
                f"{job.company} | "
                f"{job.location}"
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Searching jobs for '{keyword}' "
                        f"in '{location}'.\n\n"
                        f"Found {len(jobs)} jobs:\n"
                        + "\n".join(job_lines)
                    )
                }
            ]
        }

    return search_jobs


def create_get_job_details_tool(context: AgentContext):

    @tool(
        "get_job_details",
        "Get details of a job using its job number.",
        {
            "job_id": {
                "type": "integer",
                "description": "The job number"
            }
        }
    )
    async def get_job_details(args):

        try:
            job_id = int(args["job_id"])
        except (TypeError, ValueError):

            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Invalid job_id. "
                            "job_id must be a number."
                        )
                    }
                ]
            }

        jobs = context.state.jobs

        if job_id < 1 or job_id > len(jobs):

            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Job {job_id} was not found."
                    }
                ]
            }

        job = jobs[job_id - 1]

        context.state.current_job = job

        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Details for job {job_id}:\n"
                        f"Title: {job.title}\n"
                        f"Company: {job.company}\n"
                        f"Location: {job.location}\n"
                        f"Experience: {job.experience}\n"
                        f"Salary: {job.salary}\n"
                        f"Skills: {', '.join(job.skills)}\n"
                        f"Description: {job.description}\n"
                        f"URL: {job.url}\n"
                    )
                }
            ]
        }

    return get_job_details