"""NaukriJobSource page loop with the browser and card extractor faked out."""

import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.job_sources import naukri
from app.models.job import Job


def jobs(*urls: str) -> list[Job]:
    return [Job(title=u, company="C", location="L", description="", url=u) for u in urls]


class FakeBrowser:
    """Serves `pages` (lists of jobs) in order; records what happened."""

    pages: list[list[Job]] = []
    has_next: bool = True
    fail_on_page: int | None = None
    opened: list[str] = []

    def __init__(self, headless, timeout_ms):
        self.current = 0
        self.page = self

    async def start(self): ...
    async def open_naukri(self): ...
    async def close(self): ...

    async def search_jobs(self, keyword, location):
        self.current = 0

    def locator(self, selector):
        return FakeCards(FakeBrowser.pages[self.current])

    async def next_page_url(self):
        if not FakeBrowser.has_next or self.current + 1 >= len(FakeBrowser.pages):
            return None
        return f"https://x/page-{self.current + 2}"

    async def open_results_page(self, url):
        if FakeBrowser.fail_on_page == self.current + 2:
            raise PlaywrightTimeoutError("timeout")
        FakeBrowser.opened.append(url)
        self.current += 1


class FakeCards:
    def __init__(self, page_jobs):
        self.page_jobs = page_jobs

    async def count(self):
        return len(self.page_jobs)

    def nth(self, i):
        return self.page_jobs[i]


class FakeExtractor:
    async def extract_job(self, card):
        return card


@pytest.fixture
def fake(monkeypatch):
    FakeBrowser.pages = []
    FakeBrowser.has_next = True
    FakeBrowser.fail_on_page = None
    FakeBrowser.opened = []
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(naukri, "NaukriBrowser", FakeBrowser)
    monkeypatch.setattr(naukri, "NaukriExtractor", FakeExtractor)
    monkeypatch.setattr(naukri.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(naukri.random, "uniform", lambda low, high: high / 2)
    return slept


def get_jobs(max_pages: int) -> list[str]:
    source = naukri.NaukriJobSource(
        "Python", "Noida", max_pages=max_pages, page_delay_seconds=3.0, page_jitter_seconds=2.0
    )
    return [job.url for job in asyncio.run(source.get_jobs())]


def test_reads_up_to_max_pages_with_delay_and_jitter(fake):
    FakeBrowser.pages = [jobs("a", "b"), jobs("c"), jobs("d"), jobs("e")]

    assert get_jobs(max_pages=3) == ["a", "b", "c", "d"]
    assert FakeBrowser.opened == ["https://x/page-2", "https://x/page-3"]
    assert fake == [4.0, 4.0]  # 3.0 base + uniform(0, 2.0) faked to 1.0


def test_default_is_one_page_like_before(fake):
    FakeBrowser.pages = [jobs("a"), jobs("b")]

    source = naukri.NaukriJobSource("Python", "Noida")
    assert [job.url for job in asyncio.run(source.get_jobs())] == ["a"]
    assert FakeBrowser.opened == []


def test_stops_when_there_is_no_next_page(fake):
    FakeBrowser.pages = [jobs("a"), jobs("b")]
    FakeBrowser.has_next = False

    assert get_jobs(max_pages=3) == ["a"]
    assert fake == []


def test_stops_when_a_page_has_no_new_cards(fake):
    FakeBrowser.pages = [jobs("a", "b"), jobs("b", "a"), jobs("c")]

    assert get_jobs(max_pages=3) == ["a", "b"]
    assert FakeBrowser.opened == ["https://x/page-2"]


def test_repeated_cards_are_kept_once(fake):
    FakeBrowser.pages = [jobs("a", "b"), jobs("b", "c")]

    assert get_jobs(max_pages=2) == ["a", "b", "c"]


def test_timeout_on_a_later_page_keeps_earlier_jobs(fake):
    FakeBrowser.pages = [jobs("a"), jobs("b"), jobs("c")]
    FakeBrowser.fail_on_page = 3

    assert get_jobs(max_pages=3) == ["a", "b"]
