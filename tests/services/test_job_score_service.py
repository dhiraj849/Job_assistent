from app.services.job_score_service import JobScoreService


def test_all_scores_100_return_100():

    service = JobScoreService()

    result = service.calculate(
        skill_match=100,
        role_match=100,
        experience_match=100
    )

    assert result == 100


def test_all_scores_0_return_0():

    service = JobScoreService()

    result = service.calculate(
        skill_match=0,
        role_match=0,
        experience_match=0
    )

    assert result == 0


def test_weighted_score_is_calculated_correctly():

    service = JobScoreService()

    result = service.calculate(
        skill_match=80,
        role_match=90,
        experience_match=70
    )

    assert result == 81


def test_skill_match_has_50_percent_weight():

    service = JobScoreService()

    result = service.calculate(
        skill_match=100,
        role_match=0,
        experience_match=0
    )

    assert result == 50


def test_role_match_has_30_percent_weight():

    service = JobScoreService()

    result = service.calculate(
        skill_match=0,
        role_match=100,
        experience_match=0
    )

    assert result == 30


def test_experience_match_has_20_percent_weight():

    service = JobScoreService()

    result = service.calculate(
        skill_match=0,
        role_match=0,
        experience_match=100
    )

    assert result == 20