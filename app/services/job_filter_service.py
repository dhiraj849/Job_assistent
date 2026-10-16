import re

from app.models.candidate_profile import SearchConfig
from app.models.job import Job


def _word_pattern(keyword: str) -> re.Pattern:
    # Whole-word match: plain `in` let "rag" hit "storage" and "rest" hit
    # "interest". Lookarounds instead of \b so "c++" / "node.js" still work.
    return re.compile(rf"(?<!\w){re.escape(keyword.lower())}(?!\w)", re.IGNORECASE)


def _matches(patterns: dict[str, re.Pattern], text: str) -> list[str]:
    return [keyword for keyword, pattern in patterns.items() if pattern.search(text)]


class JobFilterService:
    """Cheap keyword pre-filter before embeddings and the LLM.

    All lists come from the profile's `search:` section.
    """

    def __init__(self, search: SearchConfig):
        self.title_keywords = {k: _word_pattern(k) for k in search.title_keywords}
        self.generic_titles = {k: _word_pattern(k) for k in search.generic_titles}
        self.supporting_skills = {k: _word_pattern(k) for k in search.supporting_skills}
        self.exclude_title_keywords = {k: _word_pattern(k) for k in search.exclude_title_keywords}

    def filter_jobs(self, jobs: list[Job]) -> list[tuple[Job, list[str]]]:
        relevant_jobs = []

        for job in jobs:
            title = job.title

            # Clearly unrelated roles are dropped even if a keyword matches
            if _matches(self.exclude_title_keywords, title):
                continue

            title_matches = _matches(self.title_keywords, title)

            skill_matches = [
                keyword
                for skill in job.skills
                for keyword in _matches(self.supporting_skills, skill)
            ]

            matched_keywords = list(dict.fromkeys(title_matches + skill_matches))

            # Strong title match is enough on its own
            if title_matches:
                relevant_jobs.append((job, matched_keywords))

            # A generic software title needs a supporting skill to count
            elif _matches(self.generic_titles, title) and skill_matches:
                relevant_jobs.append((job, matched_keywords))

        return relevant_jobs
