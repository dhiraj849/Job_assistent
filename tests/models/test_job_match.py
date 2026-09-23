import pytest
from pydantic import ValidationError

from app.models.job_match import JobMatchResult


def create_valid_match():

    return {
        "role_match": 80,
        "skill_match": 70,
        "experience_match": 90,
        "matching_skills": [
            "Python",
            "Django"
        ],
        "missing_skills": [
            "Kubernetes"
        ],
        "strengths": [
            "Strong Python experience"
        ],
        "concerns": [
            "Missing Kubernetes experience"
        ],
        "recommendation": "Good match"
    }


def test_valid_scores_are_accepted():

    result = JobMatchResult(
        **create_valid_match()
    )

    assert result.role_match == 80
    assert result.skill_match == 70
    assert result.experience_match == 90


def test_negative_role_score_is_rejected():

    data = create_valid_match()

    data["role_match"] = -1

    with pytest.raises(ValidationError):

        JobMatchResult(**data)


def test_role_score_above_100_is_rejected():

    data = create_valid_match()

    data["role_match"] = 101

    with pytest.raises(ValidationError):

        JobMatchResult(**data)


def test_negative_skill_score_is_rejected():

    data = create_valid_match()

    data["skill_match"] = -1

    with pytest.raises(ValidationError):

        JobMatchResult(**data)


def test_skill_score_above_100_is_rejected():

    data = create_valid_match()

    data["skill_match"] = 101

    with pytest.raises(ValidationError):

        JobMatchResult(**data)


def test_negative_experience_score_is_rejected():

    data = create_valid_match()

    data["experience_match"] = -1

    with pytest.raises(ValidationError):

        JobMatchResult(**data)


def test_experience_score_above_100_is_rejected():

    data = create_valid_match()

    data["experience_match"] = 101

    with pytest.raises(ValidationError):

        JobMatchResult(**data)