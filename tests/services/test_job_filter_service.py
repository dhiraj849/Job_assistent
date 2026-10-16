"""Keyword pre-filter: lists come from the profile, whole-word matching."""

from pathlib import Path

import pytest

from app.models.candidate_profile import SearchConfig
from app.models.job import Job
from app.services.job_filter_service import JobFilterService
from app.services.profile_loader import load_profile

EXAMPLE_PROFILE = Path(__file__).parents[2] / "profile.example.yaml"


def make_search(**overrides) -> SearchConfig:
    values = dict(
        keyword="Python",
        location="Noida",
        title_keywords=["python", "rag"],
        generic_titles=["software engineer"],
        supporting_skills=["rest", "django"],
        exclude_title_keywords=["frontend"],
        role_focus=["Python backend"],
    )
    return SearchConfig(**(values | overrides))


def job(title: str, skills: list[str] | None = None) -> Job:
    return Job(title=title, company="C", location="L", description="", skills=skills or [])


def kept(service: JobFilterService, *jobs: Job) -> list[str]:
    return [j.title for j, _ in service.filter_jobs(list(jobs))]


@pytest.fixture
def service():
    return JobFilterService(make_search())


def test_title_keyword_is_kept(service):
    assert kept(service, job("Senior Python Developer")) == ["Senior Python Developer"]


def test_substring_is_not_a_keyword_match(service):
    # "rag" inside "storage" used to match
    assert kept(service, job("Storage Administrator")) == []


def test_keyword_as_whole_word_still_matches(service):
    assert kept(service, job("RAG Engineer")) == ["RAG Engineer"]
    assert kept(service, job("GenAI / RAG-based search")) == ["GenAI / RAG-based search"]


def test_substring_skill_does_not_support_generic_title(service):
    # "rest" inside "interest" used to back up a generic title
    assert kept(service, job("Software Engineer", ["Interest calculation"])) == []


def test_generic_title_needs_a_supporting_skill(service):
    assert kept(service, job("Software Engineer", ["REST API", "Java"])) == ["Software Engineer"]
    assert kept(service, job("Software Engineer", ["Java"])) == []


def test_exclude_keyword_wins_over_title_keyword(service):
    assert kept(service, job("Frontend Python Developer")) == []


def test_matched_keywords_are_reported_once(service):
    [(_, matched)] = service.filter_jobs([job("Python Developer", ["Django", "django"])])
    assert matched == ["python", "django"]


def test_keywords_with_symbols_match_whole_words():
    service = JobFilterService(make_search(title_keywords=["c++", "node.js"]))
    assert kept(service, job("C++ Developer"), job("Node.js Engineer")) == [
        "C++ Developer",
        "Node.js Engineer",
    ]


def test_lists_come_from_the_profile_yaml():
    service = JobFilterService(load_profile(EXAMPLE_PROFILE).search)
    assert kept(service, job("Backend Engineer"), job("Full Stack Developer")) == ["Backend Engineer"]
