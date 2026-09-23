from app.services.job_match_level_service import JobMatchLevelService


def test_score_59_is_weak():

    service = JobMatchLevelService()

    result = service.classify(59)

    assert result == "weak"


def test_score_60_is_potential():

    service = JobMatchLevelService()

    result = service.classify(60)

    assert result == "potential"


def test_score_79_is_potential():

    service = JobMatchLevelService()

    result = service.classify(79)

    assert result == "potential"


def test_score_80_is_strong():

    service = JobMatchLevelService()

    result = service.classify(80)

    assert result == "strong"


def test_score_100_is_strong():

    service = JobMatchLevelService()

    result = service.classify(100)

    assert result == "strong"