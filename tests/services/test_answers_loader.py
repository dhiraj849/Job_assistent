from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.answers_loader import load_answers

EXAMPLE_ANSWERS = Path(__file__).parents[2] / "answers.example.yaml"

VALID_YAML = (
    "notice_period_days: 30\n"
    "current_ctc_lpa: 8.0\n"
    "expected_ctc_lpa: 12.0\n"
    "current_location: Noida\n"
    "willing_to_relocate: true\n"
    "total_experience_years: 3\n"
    "skill_years:\n"
    "  python: 3\n"
)


def write(tmp_path, text):
    file = tmp_path / "answers.yaml"
    file.write_text(text)
    return file


def test_example_answers_load():
    answers = load_answers(EXAMPLE_ANSWERS)

    assert answers.notice_period_days == 30
    assert answers.skill_years_for("python") == 3


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="answers.example.yaml"):
        load_answers(tmp_path / "does_not_exist.yaml")


def test_skill_lookup_is_case_insensitive(tmp_path):
    answers = load_answers(write(tmp_path, VALID_YAML))

    assert answers.skill_years_for("Python") == 3
    assert answers.skill_years_for("Rust") is None


def test_wrong_type_is_rejected(tmp_path):
    bad = VALID_YAML.replace("notice_period_days: 30", 'notice_period_days: "thirty"')

    with pytest.raises(ValidationError):
        load_answers(write(tmp_path, bad))


def test_negative_ctc_is_rejected(tmp_path):
    bad = VALID_YAML.replace("current_ctc_lpa: 8.0", "current_ctc_lpa: -5")

    with pytest.raises(ValidationError):
        load_answers(write(tmp_path, bad))


def test_expected_below_current_is_rejected(tmp_path):
    bad = VALID_YAML.replace("expected_ctc_lpa: 12.0", "expected_ctc_lpa: 6.0")

    with pytest.raises(ValidationError, match="expected_ctc_lpa"):
        load_answers(write(tmp_path, bad))


def test_unknown_key_is_rejected(tmp_path):
    bad = VALID_YAML.replace("notice_period_days", "notice_peroid_days")

    with pytest.raises(ValidationError):
        load_answers(write(tmp_path, bad))
