"""Field mapper on saved company pages (no browser)."""

from pathlib import Path

import pytest

from app.browser.company_form_mapper import NO_RULE, ai_forbidden_reason, map_field, map_form
from app.browser.company_portal import FormField, application_form, parse_form_fields
from app.models.application_answers import ApplicationAnswers, ContactAnswers
from app.services.learned_answers import LearnedAnswers

FIXTURES = Path(__file__).parent.parent / "fixtures" / "company_sites"


@pytest.fixture
def resume(tmp_path) -> Path:
    path = tmp_path / "resume.pdf"
    path.write_bytes(b"%PDF-1.4")
    return path


@pytest.fixture
def answers(resume) -> ApplicationAnswers:
    return ApplicationAnswers(
        notice_period_days=30,
        current_ctc_lpa=8,
        expected_ctc_lpa=12,
        current_location="Noida",
        willing_to_relocate=True,
        total_experience_years=6,
        contact=ContactAnswers(
            first_name="Asha",
            last_name="Verma",
            email="asha@example.com",
            phone="+91 98765 43210",
            resume_path=resume,
            linkedin_url="https://www.linkedin.com/in/asha",
        ),
    )


def form_of(fixture: str) -> list[FormField]:
    fields = parse_form_fields((FIXTURES / f"{fixture}.html").read_text(encoding="utf-8"))
    return application_form(fields)


def values(mapped) -> dict[str, str | None]:
    return {m.field.name: (m.answer.value if m.answer else None) for m in mapped}


def test_real_kmgus_form(answers, resume):
    mapped = map_form(form_of("generic_kmgus_form_open"), answers)

    assert values(mapped) == {
        "Name": "Asha Verma",
        "Email": "asha@example.com",
        "mobile": "+91 98765 43210",
        "UploadResume": str(resume),
        # Consents are never ticked; the honeypot is never filled.
        "consent_email_communication": None,
        "related_to_products": None,
        "consent_contacted": None,
        "_wpcf7_ak_hp_textarea": None,
    }
    reasons = {m.field.name: m.reason for m in mapped}
    assert reasons["consent_contacted"] == "checkbox (consent): you decide"
    assert reasons["_wpcf7_ak_hp_textarea"].startswith("hidden field")


def test_real_zaax_form(answers, resume):
    """zaax.com/submit-resume (job 1065, 2026-10-15): one shared resume form for every job."""
    mapped = map_form(form_of("generic_zaax_submit_resume"), answers)
    got = values(mapped)
    reasons = {m.field.name: m.reason for m in mapped}

    assert (got["candidate_name"], got["email"], got["mobile"]) == ("Asha Verma", "asha@example.com", "+91 98765 43210")
    assert got["vita_file"] == str(resume)
    assert got["clocation"] == "Noida"
    # A landline is not my mobile (it got the mobile number before this fix).
    assert got["landline"] is None and reasons["landline"] == NO_RULE
    # 6 years fits both "3+ Years" and "5-8 Years": ambiguous, so left for me.
    assert got["texp"] is None
    assert reasons["dob"] == "date field: not filled automatically"
    assert reasons["honeypot"].startswith("hidden field")
    assert reasons["gender"] == NO_RULE and ai_forbidden_reason(next(m.field for m in mapped if m.field.name == "gender"))


@pytest.mark.parametrize("label", ["Landline Number", "Alternate phone", "Emergency contact number", "Fax"])
def test_other_phone_numbers_are_not_my_mobile(answers, label):
    assert map_field(FormField(kind="tel", label=label), answers).answer is None


def test_closed_modal_has_no_form_to_fill():
    # Before the click the email field is hidden: nothing to fill.
    assert form_of("generic_kmgus") == []


def test_greenhouse_split_name_linkedin_and_notice_select(answers):
    mapped = {m.field.label: m for m in map_form(form_of("synthetic_greenhouse"), answers)}

    assert mapped["First Name"].answer.value == "Asha"
    assert mapped["Last Name"].answer.value == "Verma"
    assert mapped["LinkedIn Profile"].answer.value == "https://www.linkedin.com/in/asha"
    notice = mapped["What is your notice period?"].answer
    assert (notice.value, notice.rule) == ("30 days", "screening question")


def test_lever_full_name_and_relocation_radio(answers):
    mapped = {m.field.label: m for m in map_form(form_of("synthetic_lever"), answers)}

    assert mapped["Full name"].answer.rule == "full_name"
    assert mapped["Are you willing to relocate to Bangalore?"].answer.value == "Yes"
    # "Current company" is not in answers.yaml: left for a human.
    assert mapped["Current company"].answer is None


@pytest.mark.parametrize(
    "label",
    ["Company name", "Father's name", "Name of your college", "Referrer name"],
)
def test_other_names_are_not_the_full_name(answers, label):
    assert map_field(FormField(kind="text", label=label), answers).answer is None


def test_ambiguous_field_gets_no_answer(answers):
    mapped = map_field(FormField(kind="text", label="Email or phone"), answers)
    assert mapped.answer is None
    assert mapped.reason == "ambiguous: matches email, phone"


def test_missing_resume_file_is_reported(answers, resume):
    resume.unlink()
    mapped = map_field(FormField(kind="file", label="Upload CV"), answers)
    assert mapped.answer is None and mapped.reason.startswith("resume: file not found")


def test_no_contact_block(answers):
    answers = answers.model_copy(update={"contact": None})
    mapped = map_field(FormField(kind="email", label="Email"), answers)
    assert mapped.reason == "email: no contact block in answers.yaml"


def test_other_file_uploads_and_unknown_fields_stay_empty(answers):
    assert map_field(FormField(kind="file", label="Cover letter"), answers).answer is None
    assert map_field(FormField(kind="text", label="Favourite colour"), answers).answer is None
    assert map_field(FormField(kind="date", label="Date of birth"), answers).answer is None


# --- Learned answers and AI limits ---------------------------------------------------


def test_unknown_field_uses_my_learned_answer(answers):
    learned = LearnedAnswers()
    learned.add("Highest qualification", "B.Tech")
    field = FormField(kind="text", label="Highest Qualification *")

    assert map_field(field, answers).reason == NO_RULE
    mapped = map_field(field, answers, learned)
    assert (mapped.answer.value, mapped.answer.rule) == ("B.Tech", "learned")


def test_learned_answer_must_fit_the_options(answers):
    learned = LearnedAnswers()
    learned.add("Degree", "b.tech")
    fits = FormField(kind="select", label="Degree", options=("Select", "B.Tech", "M.Tech"))
    misses = FormField(kind="select", label="Degree", options=("BE", "ME"))

    assert map_field(fits, answers, learned).answer.value == "B.Tech"
    assert map_field(misses, answers, learned).answer is None


def test_fixed_rules_win_over_learned_answers(answers):
    learned = LearnedAnswers()
    learned.add("Email", "other@example.com")
    assert map_field(FormField(kind="email", label="Email"), answers, learned).answer.value == "asha@example.com"


@pytest.mark.parametrize(
    "label",
    ["Gender", "Date of Birth", "Caste category", "Expected salary", "Do you need visa sponsorship?",
     "I agree to the terms", "Have you ever been convicted?"],
)
def test_ai_never_answers_these(label):
    assert ai_forbidden_reason(FormField(kind="text", label=label)) is not None


@pytest.mark.parametrize("label", ["Highest qualification", "Current employer", "Languages known"])
def test_ai_may_suggest_for_plain_facts(label):
    assert ai_forbidden_reason(FormField(kind="text", label=label)) is None


def test_real_greenhouse_board(answers, resume):
    mapped = {m.field.id: m for m in map_form(form_of("greenhouse_tower_frame"), answers)}

    assert mapped["first_name"].answer.value == "Asha"
    assert mapped["email"].answer.value == "asha@example.com"
    assert mapped["phone"].answer.value == "+91 98765 43210"
    assert mapped["resume"].answer.value == str(resume)  # label "Attach", id "resume"
    assert mapped["cover_letter"].answer is None
    assert mapped["question_54153730"].answer.value == "https://www.linkedin.com/in/asha"
    # Dropdowns (country, Yes/No questions) are left for me in the browser.
    assert mapped["country"].reason == "dropdown with search: you pick it in the browser"
    assert mapped["question_54153733"].answer is None


@pytest.mark.parametrize(
    "label",
    [
        "Are you currently authorized to work for all employers in the United States?",
        "Are you or have you been entrusted with a position in any government?",
        "Are you an immediate family member of someone holding such a position?",
    ],
)
def test_ai_never_answers_legal_declarations(label):
    assert ai_forbidden_reason(FormField(kind="text", label=label)) is not None


def test_referrer_name_question_is_never_my_name(answers):
    # Real Greenhouse label (Tower Research, 2026-10-15): filling my own name
    # here would say I referred myself.
    label = ("Were you referred to this role by a current Tower Research Capital employee? "
             "If so, please provide their name.")
    assert map_field(FormField(kind="text", label=label), answers).answer is None
    for other in ("Employee name", "Emergency contact name", "Recruiter name"):
        assert map_field(FormField(kind="text", label=other), answers).answer is None
    assert map_field(FormField(kind="text", label="Your name"), answers).answer.value == "Asha Verma"
