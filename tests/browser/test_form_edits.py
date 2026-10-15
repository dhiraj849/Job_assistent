"""Which browser edits may become learned answers (no browser: values as the page reports them)."""

from pathlib import Path

import pytest

from app.browser.company_form_mapper import MappedField, map_form
from app.browser.company_portal import FormField, application_form, parse_form_fields
from app.browser.form_edits import browser_edits
from app.models.application_answers import ApplicationAnswers, ContactAnswers
from app.services.learned_answers import LearnedAnswers

ZAAX = Path(__file__).parent.parent / "fixtures" / "company_sites" / "generic_zaax_submit_resume.html"


@pytest.fixture
def mapped(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    answers = ApplicationAnswers(
        notice_period_days=30,
        current_ctc_lpa=8,
        expected_ctc_lpa=12,
        current_location="Noida",
        willing_to_relocate=True,
        total_experience_years=6,
        contact=ContactAnswers(
            first_name="Asha", last_name="Verma", email="asha@example.com",
            phone="+91 98765 43210", resume_path=resume,
        ),
    )
    form = application_form(parse_form_fields(ZAAX.read_text(encoding="utf-8")))
    return map_form(form, answers)


def value(name, text, kind="text", id_=None):
    return {"name": name, "id": name if id_ is None else id_, "type": kind, "value": text}


def edited(edits):
    return {e.field.name: e.value for e in edits}


def test_my_new_answers_are_offered(mapped):
    page = [
        value("gender", "Female", "select-one"),
        value("texp", "5-8 Years", "select-one"),
        value("nationality", "Indian"),
    ]
    assert edited(browser_edits(mapped, page, LearnedAnswers())) == {
        "gender": "Female", "texp": "5-8 Years", "nationality": "Indian",
    }


def test_honeypot_placeholder_and_unknown_option_are_skipped(mapped):
    page = [
        value("honeypot", "bot", id_=""),
        value("gender", "", "select-one"),  # "Select": its option value is empty
        value("texp", "7 years", "select-one"),  # not one of the options
    ]
    assert browser_edits(mapped, page, LearnedAnswers()) == []


def test_page_defaults_are_not_my_edits(mapped):
    baseline = [value("country2", "India", "select-one")]
    assert browser_edits(mapped, baseline, LearnedAnswers(), baseline) == []
    changed = [value("country2", "Nepal", "select-one")]
    assert edited(browser_edits(mapped, changed, LearnedAnswers(), baseline)) == {"country2": "Nepal"}


def test_fields_from_answers_yaml_are_only_reported(mapped):
    page = [value("clocation", "Pune"), value("mobile", "+91 98765 43210")]
    edits = browser_edits(mapped, page, LearnedAnswers())
    assert [(e.field.name, e.fixed_rule, e.before) for e in edits] == [("clocation", "screening question", "Noida")]


def test_answer_already_learned_is_not_offered_again(mapped):
    learned = LearnedAnswers()
    learned.add("Nationality", "Indian")
    assert browser_edits(mapped, [value("nationality", "Indian")], learned) == []


def test_secrets_and_checked_radio(mapped):
    otp = MappedField(field=FormField(kind="text", label="Enter OTP", name="otp"), answer=None)
    shift = MappedField(field=FormField(kind="radio", label="Shift", name="shift", options=("Day", "Night")), answer=None)
    page = [value("otp", "123456"), {"name": "shift", "id": "", "type": "radio", "value": "Night"}]
    assert edited(browser_edits([otp, shift], page, LearnedAnswers())) == {"shift": "Night"}
