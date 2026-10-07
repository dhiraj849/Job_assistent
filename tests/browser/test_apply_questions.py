"""Question mapper: known questions get the answers.yaml value, anything else None."""

import pytest

from app.browser.apply_questions import Question, map_question
from app.models.application_answers import ApplicationAnswers

ANSWERS = ApplicationAnswers(
    notice_period_days=30,
    current_ctc_lpa=10,
    expected_ctc_lpa=14.5,
    current_location="Noida",
    willing_to_relocate=True,
    total_experience_years=4,
    skill_years={"Python": 4, "Django": 2.5, "C++": 1},
)


def ask(text: str, options: list[str] | None = None, multi: bool = False) -> str | None:
    return map_question(Question(text, options or [], multi), ANSWERS)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("What is your notice period?", "30 days"),
        ("Notice period (in days)?", "30"),
        ("Notice period in months", "1"),
        ("How soon can you join?", "30 days"),
        ("What is your current CTC?", "10 LPA"),
        ("Current CTC in lakhs", "10"),
        ("Current annual salary in INR", "1000000"),
        ("What is your expected CTC?", "14.5 LPA"),
        ("What is your current location?", "Noida"),
        ("Are you willing to relocate?", "Yes"),
        ("How many years of experience do you have in Python?", "4"),
        ("Years of experience in django", "2.5"),
        ("How many years of experience in C++?", "1"),
        ("What is your total experience?", "4"),
        ("How many years of experience do you have?", "4"),
    ],
)
def test_known_free_text_questions(text, expected):
    assert ask(text) == expected


def test_notice_period_option():
    options = ["15 Days or less", "1 Month", "2 Months", "3 Months", "More than 3 Months"]
    assert ask("What is your notice period?", options) == "1 Month"


def test_ctc_range_option():
    options = ["0-5 Lakhs", "5-10 Lakhs", "10.5-15 Lakhs", "15+ Lakhs"]
    assert ask("Expected CTC?", options) == "10.5-15 Lakhs"


def test_skill_years_option():
    options = ["0-1 years", "2-3 years", "4-6 years", "7+ years"]
    assert ask("Experience in Python?", options) == "4-6 years"


def test_relocate_option():
    assert ask("Willing to relocate to Pune?", ["Yes", "No"]) == "Yes"


def test_location_option():
    assert ask("Where are you currently located?", ["Delhi", "noida", "Pune"]) == "noida"
    assert ask("Your current location", ["Delhi", "Gurgaon"]) is None  # Noida not offered


@pytest.mark.parametrize(
    "text",
    [
        "Why do you want to join us?",
        "How many years of experience do you have in Kafka?",  # skill not in answers.yaml
        "Years of experience in Python and Django?",  # two skills: no single number
        "Years of relevant experience?",
        "Are you serving your notice period?",  # yes/no, must not get "30 days"
        "Can you join within 15 days?",
        "Is your current location Noida?",
        "Where would you like to relocate?",  # not yes/no, must not get "Yes"
        "What is your CTC?",  # current or expected? unclear
        "Expected CTC compared to current CTC?",  # two rules match
        "",
    ],
)
def test_unknown_or_ambiguous_questions_need_a_human(text):
    assert ask(text) is None


def test_no_option_fits():
    # 30 days is neither "15 days or less" nor "2 months".
    assert ask("Notice period?", ["15 Days or less", "2 Months"]) is None


def test_two_options_fit():
    assert ask("Expected CTC?", ["10-15 Lakhs", "14-20 Lakhs"]) is None


def test_options_without_units_need_a_human():
    assert ask("Current CTC?", ["5-10", "10-15"]) is None


def test_checkbox_question_needs_a_human():
    assert ask("Notice period?", ["1 Month"], multi=True) is None
