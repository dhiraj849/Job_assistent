import asyncio
import random
import time

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser.naukri_browser import JOB_CARD, NaukriBrowser
from app.job_sources.base import JobSource
from app.job_sources.naukri_extractor import NaukriExtractor
from app.models.job import Job

logger = structlog.get_logger(__name__)


def _job_key(job: Job) -> str:
    # The URL identifies a posting; title|company only for a card without a link.
    return job.url or f"{job.title}|{job.company}"


class NaukriJobSource(JobSource):

    def __init__(
        self,
        keyword: str,
        location: str,
        headless: bool = False,
        timeout_ms: int = 20000,
        max_pages: int = 1,
        page_delay_seconds: float = 0.0,
        page_jitter_seconds: float = 0.0,
    ):
        self.keyword = keyword
        self.location = location
        self.headless = headless
        self.timeout_ms = timeout_ms

        # Defaults read one page, like before; the discovery activity passes
        # the MAX_SEARCH_PAGES / SEARCH_PAGE_* settings.
        self.max_pages = max_pages
        self.page_delay_seconds = page_delay_seconds
        self.page_jitter_seconds = page_jitter_seconds

        self.extractor = NaukriExtractor()

    async def get_jobs(self) -> list[Job]:

        log = logger.bind(keyword=self.keyword, location=self.location)

        browser = NaukriBrowser(
            headless=self.headless,
            timeout_ms=self.timeout_ms,
        )

        await browser.start()

        try:

            await browser.open_naukri()

            log.info("search_started", max_pages=self.max_pages)
            start = time.perf_counter()

            try:
                await browser.search_jobs(
                    keyword=self.keyword,
                    location=self.location,
                )
            except PlaywrightTimeoutError:
                log.warning(
                    "no_job_cards_found",
                    timeout_ms=self.timeout_ms,
                    url=browser.page.url,
                )
                return []

            log.info(
                "search_page_loaded",
                search_duration_ms=round((time.perf_counter() - start) * 1000),
            )

            jobs: list[Job] = []
            seen: set[str] = set()

            for page_no in range(1, self.max_pages + 1):

                page_jobs = await self._extract_page(browser, log, page_no)
                new_jobs = [job for job in page_jobs if _job_key(job) not in seen]

                # Naukri can repeat a page (e.g. past the last one); nothing new
                # means reading further would only cost requests.
                if not new_jobs:
                    log.info("search_page_no_new_jobs", page=page_no)
                    break

                seen.update(_job_key(job) for job in new_jobs)
                jobs.extend(new_jobs)

                if page_no == self.max_pages:
                    break

                next_url = await browser.next_page_url()
                if next_url is None:
                    log.info("search_no_next_page", page=page_no)
                    break

                # Polite, uneven gap between pages (this runs in an activity,
                # so random is fine).
                await asyncio.sleep(
                    self.page_delay_seconds + random.uniform(0, self.page_jitter_seconds)
                )

                try:
                    await browser.open_results_page(next_url)
                except PlaywrightTimeoutError:
                    # Keep what we already have instead of failing the whole run.
                    log.warning("search_page_timeout", page=page_no + 1, url=next_url)
                    break

            log.info("jobs_extracted", count=len(jobs), pages=page_no)

            return jobs

        finally:
            await browser.close()

    async def _extract_page(self, browser: NaukriBrowser, log, page_no: int) -> list[Job]:
        job_cards = browser.page.locator(JOB_CARD)
        count = await job_cards.count()

        log.info("job_cards_found", page=page_no, count=count)

        jobs = []

        for i in range(count):

            job_card = job_cards.nth(i)

            try:
                job = await self.extractor.extract_job(job_card)
                jobs.append(job)

                log.debug(
                    "job_extracted",
                    page=page_no,
                    index=i + 1,
                    total=count,
                    title=job.title,
                    experience=job.experience,
                    skills=job.skills,
                )

            except Exception:
                log.warning(
                    "job_extraction_failed",
                    page=page_no,
                    index=i + 1,
                    total=count,
                    exc_info=True,
                )

        return jobs
