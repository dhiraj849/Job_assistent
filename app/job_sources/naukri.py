import time

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser.naukri_browser import JOB_CARD, NaukriBrowser
from app.job_sources.base import JobSource
from app.job_sources.naukri_extractor import NaukriExtractor
from app.models.job import Job

logger = structlog.get_logger(__name__)


class NaukriJobSource(JobSource):

    def __init__(
        self,
        keyword: str,
        location: str,
        headless: bool = False,
        timeout_ms: int = 20000,
    ):
        self.keyword = keyword
        self.location = location
        self.headless = headless
        self.timeout_ms = timeout_ms

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

            log.info("search_started")
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

            search_duration_ms = round((time.perf_counter() - start) * 1000)

            job_cards = browser.page.locator(JOB_CARD)
            count = await job_cards.count()

            log.info(
                "job_cards_found",
                count=count,
                search_duration_ms=search_duration_ms,
            )

            jobs = []

            for i in range(count):

                job_card = job_cards.nth(i)

                try:
                    job = await self.extractor.extract_job(job_card)
                    jobs.append(job)

                    log.debug(
                        "job_extracted",
                        index=i + 1,
                        total=count,
                        title=job.title,
                        experience=job.experience,
                        skills=job.skills,
                    )

                except Exception:
                    log.warning(
                        "job_extraction_failed",
                        index=i + 1,
                        total=count,
                        exc_info=True,
                    )

            log.info("jobs_extracted", count=len(jobs))

            return jobs

        finally:
            await browser.close()