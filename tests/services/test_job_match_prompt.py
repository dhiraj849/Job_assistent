"""The LLM match prompt takes its role focus from the profile."""

from pathlib import Path

from app.models.job import Job
from app.services.job_match_service import build_prompt
from app.services.profile_loader import load_profile

EXAMPLE_PROFILE = Path(__file__).parents[2] / "profile.example.yaml"
JOB = Job(title="T", company="C", location="L", description="D")


def test_role_focus_comes_from_profile():
    profile = load_profile(EXAMPLE_PROFILE)
    profile.search.role_focus = ["Kotlin mobile apps"]

    prompt = build_prompt(profile, JOB)

    assert "- Kotlin mobile apps" in prompt
    assert "Python backend development" not in prompt


def test_search_section_is_not_dumped_into_the_candidate_block():
    prompt = build_prompt(load_profile(EXAMPLE_PROFILE), JOB)

    assert "title_keywords" not in prompt
    assert "exclude_title_keywords" not in prompt
