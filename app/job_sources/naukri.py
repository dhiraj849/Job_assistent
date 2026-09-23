from app.browser.naukri_browser import NaukriBrowser
from app.job_sources.base import JobSource
from app.job_sources.naukri_extractor import NaukriExtractor
from app.models.job import Job
import structlog

logger = structlog.get_logger(__name__)

class NaukriJobSource(JobSource):

    def __init__(
        self,
        keyword: str,
        location: str
    ):
        self.keyword = keyword
        self.location = location

        self.extractor = NaukriExtractor()

    async def get_jobs(self) -> list[Job]:

        browser = NaukriBrowser()

        await browser.start()

        try:

            # ----------------------------------------
            # Open Naukri
            # ----------------------------------------

            await browser.open_naukri()

            # ----------------------------------------
            # Search Jobs
            # ----------------------------------------

            await browser.search_jobs(
                keyword=self.keyword,
                location=self.location
            )

            await browser.page.get_by_text(
                "Search",
                exact=True
            ).click()

            await browser.page.wait_for_timeout(
                5000
            )

            # ----------------------------------------
            # Find Job Cards
            # ----------------------------------------

            job_cards = browser.page.locator(
                ".srp-jobtuple-wrapper"
            )

            count = await job_cards.count()

            logger.info("job_cards_found", count=count)

            jobs = []

            # ----------------------------------------
            # Extract Jobs
            # ----------------------------------------

            for i in range(count):

                job_card = job_cards.nth(i)

                try:

                    job = await self.extractor.extract_job(
                        job_card
                    )

                    jobs.append(job)

                    logger.debug(
                        "job_extracted",
                        index=i + 1,
                        total=count,
                        title=job.title,
                        experience=job.experience,
                        skills=job.skills,
                    )

                except Exception:

                    logger.warning(
                        "job_extraction_failed",
                        index=i + 1,
                        total=count,
                        exc_info=True
                    )

            logger.info(
                "jobs_extraction_complete",
                count=len(jobs)
            )

            return jobs

        finally:

            await browser.close()