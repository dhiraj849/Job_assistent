from app.agent.state import AgentState
from app.job_sources.naukri import NaukriJobSource


async def search_jobs(state: AgentState):

    job_source = NaukriJobSource(
        keyword=state.candidate.search.keyword,
        location=state.candidate.search.location
    )

    jobs = await job_source.get_jobs()

    state.jobs = jobs

    return state

from app.models.job import Job


def demo_search_jobs(state: AgentState):

    job = Job(
        title="Python Backend Engineer",
        company="Demo Company",
        location="Noida",
        description="Python backend development",
        skills=[
            "Python",
            "Django",
            "PostgreSQL"
        ]
    )

    state.jobs = [job]

    return state

from app.services.job_filter_service import JobFilterService
def filter_jobs(state: AgentState):

    filter_service = JobFilterService(state.candidate.search)

    filtered_jobs = filter_service.filter_jobs(
        state.jobs
    )

    state.jobs = [
        job
        for job, matched_keywords in filtered_jobs
    ]

    return state

from app.models.job_match import JobMatchResult
from app.models.job_match_item import JobMatchItem


def demo_match_jobs(state: AgentState):

    matches = []

    for job in state.jobs:

        result = JobMatchResult(
            role_match=90,
            skill_match=85,
            experience_match=80,
            matching_skills=[
                "Python",
                "Django",
                "PostgreSQL"
            ],
            missing_skills=[
                "AWS"
            ],
            strengths=[
                "Strong Python backend alignment"
            ],
            concerns=[
                "AWS experience is not mentioned"
            ],
            recommendation="Good match"
        )

        match_item = JobMatchItem(
            job=job,
            match=result,
            overall_score=0,
            match_level="pending"
        )

        matches.append(match_item)

    state.matches = matches

    return state

from app.services.job_score_service import JobScoreService


def score_matches(state: AgentState):

    score_service = JobScoreService()

    for item in state.matches:

        item.overall_score = score_service.calculate(
            skill_match=item.match.skill_match,
            role_match=item.match.role_match,
            experience_match=item.match.experience_match
        )

    return state
from app.services.job_match_level_service import JobMatchLevelService


def classify_matches(state: AgentState):

    level_service = JobMatchLevelService()

    for item in state.matches:

        item.match_level = level_service.classify(
            item.overall_score
        )

    return state

from app.services.job_ranking_service import JobRankingService


def rank_matches(state: AgentState):

    ranking_service = JobRankingService()

    state.ranked_jobs = ranking_service.rank(
        state.matches
    )

    return state