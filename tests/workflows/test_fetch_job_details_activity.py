"""fetch_job_details activity with the browser, DB and delay faked out."""

import asyncio
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from app.models.job import Job
from app.models.job_details import JobDetails
from app.workflows import activities

FIXTURE = Path(__file__).parent.parent / "fixtures" / "naukri" / "job_detail_37.html"
SNIPPET_JOB = Job(title="T", company="C", location="L", description="snippet", url="https://x/37")


@pytest.fixture
def fake_io(monkeypatch):
    """Fake DB load/save and page fetch; returns what happened."""
    state = {"job": SNIPPET_JOB, "fetched": [], "saved": []}

    async def get_job(job_id):
        return state["job"]

    async def fetch_job_page(url, headless, timeout_ms):
        state["fetched"].append(url)
        return state["html"]

    class Repo:
        def __init__(self, session):
            pass

        async def save_details(self, job_id, page):
            state["saved"].append(page)
            state["job"] = SNIPPET_JOB.model_copy(
                update={"description": page.description, "details": page.details}
            )

    class Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(activities, "_get_job", get_job)
    monkeypatch.setattr(activities, "fetch_job_page", fetch_job_page)
    monkeypatch.setattr(activities, "JobRepository", Repo)
    monkeypatch.setattr(activities, "SessionLocal", Session)
    monkeypatch.setattr(activities.settings, "DETAIL_PAGE_DELAY_SECONDS", 0)
    monkeypatch.setattr(activities.settings, "DETAIL_PAGE_JITTER_SECONDS", 0)
    return state


def run(job_id: int = 37) -> Job:
    return asyncio.run(ActivityEnvironment().run(activities.fetch_job_details, job_id))


def test_reads_parses_and_saves_the_page(fake_io):
    fake_io["html"] = FIXTURE.read_text(encoding="utf-8")

    job = run()

    assert fake_io["fetched"] == ["https://x/37"]
    assert len(fake_io["saved"]) == 1
    assert job.details.source == "json_ld"
    assert len(job.description) > 500


def test_sleeps_base_delay_plus_random_jitter(fake_io, monkeypatch):
    fake_io["html"] = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(activities.settings, "DETAIL_PAGE_DELAY_SECONDS", 3.0)
    monkeypatch.setattr(activities.settings, "DETAIL_PAGE_JITTER_SECONDS", 2.0)
    uniform_args, slept = [], []

    def fake_uniform(low, high):
        uniform_args.append((low, high))
        return 1.25

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(activities.random, "uniform", fake_uniform)
    monkeypatch.setattr(activities.asyncio, "sleep", fake_sleep)

    run()

    assert uniform_args == [(0, 2.0)]
    assert slept == [4.25]


def test_already_fetched_job_makes_no_request(fake_io):
    fake_io["job"] = SNIPPET_JOB.model_copy(update={"details": JobDetails(source="json_ld")})

    run()

    assert fake_io["fetched"] == []
    assert fake_io["saved"] == []


def test_unparseable_page_is_non_retryable_and_saves_nothing(fake_io):
    fake_io["html"] = "<html><body>Access Denied</body></html>"

    with pytest.raises(ApplicationError) as error:
        run()

    assert error.value.non_retryable
    assert error.value.type == "DetailParseError"
    assert fake_io["saved"] == []
