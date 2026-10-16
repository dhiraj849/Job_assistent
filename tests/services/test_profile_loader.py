from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.profile_loader import load_profile

EXAMPLE_PROFILE = Path(__file__).parents[2] / "profile.example.yaml"


def test_example_profile_loads():
    profile = load_profile(EXAMPLE_PROFILE)

    assert profile.experience_years == 5
    assert "Python" in profile.skills
    assert profile.search.keyword == "Python Backend Engineer"
    assert "rag" in profile.search.title_keywords
    assert profile.search.role_focus


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="profile.example.yaml"):
        load_profile(tmp_path / "does_not_exist.yaml")


def test_negative_experience_is_rejected(tmp_path):
    bad_file = tmp_path / "profile.yaml"
    bad_file.write_text(
        "name: Test\n"
        "experience_years: -3\n"
        "education: B.Sc\n"
        "skills: [Python]\n"
    )

    with pytest.raises(ValidationError):
        load_profile(bad_file)

def test_missing_search_section_is_rejected(tmp_path):
    # No hidden defaults: the filter must come from the YAML
    bad_file = tmp_path / "profile.yaml"
    bad_file.write_text("name: Test\nexperience_years: 3\neducation: B.Sc\nskills: [Python]\n")

    with pytest.raises(ValidationError, match="search"):
        load_profile(bad_file)
