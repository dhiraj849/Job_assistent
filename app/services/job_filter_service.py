from app.models.job import Job


class JobFilterService:

    def __init__(self):

        self.title_keywords = [
            "python",
            "backend",
            "back end",
            "django",
            "fastapi",
            "flask",
            "ai engineer",
            "ml engineer",
            "machine learning",
            "genai",
            "generative ai",
            "rag"
        ]

        self.supporting_skills = [
            "python",
            "django",
            "fastapi",
            "flask",
            "rest api",
            "rest",
            "backend",
            "postgresql",
            "mysql",
            "mongodb",
            "aws",
            "docker"
        ]

        self.exclude_title_keywords = [
            "frontend",
            "front end",
            "full stack",
            "fullstack",
            "ssh engineer",
            "object engineer"
        ]

    def filter_jobs(
        self,
        jobs: list[Job]
    ) -> list[tuple[Job, list[str]]]:

        relevant_jobs = []

        for job in jobs:

            title = job.title.lower()

            skills = [
                skill.lower()
                for skill in job.skills
            ]

            # -----------------------------
            # Exclude clearly unrelated roles
            # -----------------------------

            excluded = any(
                keyword in title
                for keyword in self.exclude_title_keywords
            )

            if excluded:
                continue

            # -----------------------------
            # Check job title
            # -----------------------------

            title_matches = []

            for keyword in self.title_keywords:

                if keyword in title:
                    title_matches.append(keyword)

            # -----------------------------
            # Check supporting skills
            # -----------------------------

            skill_matches = []

            for skill in skills:

                for keyword in self.supporting_skills:

                    if keyword in skill:
                        skill_matches.append(keyword)

            # Remove duplicates
            matched_keywords = list(
                set(title_matches + skill_matches)
            )

            # -----------------------------
            # Decide whether job is relevant
            # -----------------------------

            # Strong title match
            if title_matches:

                relevant_jobs.append(
                    (
                        job,
                        matched_keywords
                    )
                )

            # Generic software role needs
            # supporting technical skills
            elif (
                ("software developer" in title
                 or "software engineer" in title)
                and skill_matches
            ):

                relevant_jobs.append(
                    (
                        job,
                        matched_keywords
                    )
                )

        return relevant_jobs