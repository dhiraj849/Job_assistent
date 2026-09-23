from playwright.async_api import Locator

from app.models.job import Job


class NaukriExtractor:

    async def extract_job(
        self,
        job_card: Locator
    ) -> Job:

        title = await job_card.locator(
            ".title"
        ).inner_text()

        company = await job_card.locator(
            ".comp-name"
        ).inner_text()

        location = await job_card.locator(
            ".loc"
        ).inner_text()

        description = await job_card.locator(
            ".job-desc"
        ).inner_text()

        # --------------------------------------------
        # Experience
        # --------------------------------------------

        experience = None

        experience_locator = job_card.locator(
            ".exp"
        )

        if await experience_locator.count() > 0:

            experience = await experience_locator.inner_text()

        # --------------------------------------------
        # Job URL
        # --------------------------------------------

        url = None

        title_link = job_card.locator(
            "a.title"
        )

        if await title_link.count() > 0:

            url = await title_link.get_attribute(
                "href"
            )

        # --------------------------------------------
        # Skills
        # --------------------------------------------

        skills = []

        skill_locators = job_card.locator(
            ".tags-gt .tag-li"
        )

        skill_count = await skill_locators.count()

        for i in range(skill_count):

            skill = await skill_locators.nth(i).inner_text()

            skills.append(
                skill.strip()
            )

        # --------------------------------------------
        # Create Job
        # --------------------------------------------

        return Job(
            title=title.strip(),
            company=company.strip(),
            location=location.strip(),
            experience=(
                experience.strip()
                if experience
                else None
            ),
            description=description.strip(),
            skills=skills,
            url=url
        )