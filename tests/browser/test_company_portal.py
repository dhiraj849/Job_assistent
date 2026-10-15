"""Portal detection, field reading and hard stops on saved company pages (no browser)."""

from pathlib import Path

import pytest

from app.browser.company_portal import (
    PortalType,
    detect_portal,
    find_job_opener,
    find_job_page_link,
    inspect_page,
    parse_form_fields,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "company_sites"

GREENHOUSE_URL = "https://boards.greenhouse.io/acme/jobs/123"
LEVER_URL = "https://jobs.lever.co/acme/abc-123/apply"
WORKDAY_URL = "https://acme.wd3.myworkdayjobs.com/en-US/careers/login"
COMPANY_URL = "https://careers.acme.example/jobs/42"


def html(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def by_label(fields, label):
    return next(f for f in fields if f.label == label)


# --- Portal type ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        (GREENHOUSE_URL, PortalType.GREENHOUSE),
        ("https://job-boards.greenhouse.io/acme/jobs/1", PortalType.GREENHOUSE),
        (LEVER_URL, PortalType.LEVER),
        ("https://jobs.eu.lever.co/acme/1", PortalType.LEVER),
        (WORKDAY_URL, PortalType.WORKDAY),
        ("https://jobs.smartrecruiters.com/Acme/1", PortalType.SMARTRECRUITERS),
        ("https://careers-acme.icims.com/jobs/1/job", PortalType.ICIMS),
        ("https://acme.darwinbox.in/ms/candidate/careers", PortalType.DARWINBOX),
        ("https://acme.keka.com/careers/jobdetails/1", PortalType.KEKA),
        ("https://careers.zohorecruit.in/jobs/Careers/1", PortalType.ZOHO_RECRUIT),
    ],
)
def test_portal_is_detected_from_the_url(url, expected):
    assert detect_portal(url, "<html></html>") == expected


def test_lookalike_domain_is_not_a_portal():
    # Domain-boundary match: "notlever.co" must not count as Lever.
    assert detect_portal("https://notlever.co/apply", "<html></html>") == PortalType.UNKNOWN


def test_embedded_greenhouse_is_detected_from_the_html():
    assert detect_portal(COMPANY_URL, html("synthetic_embedded_greenhouse")) == PortalType.GREENHOUSE


def test_application_form_on_a_company_page_is_generic():
    assert detect_portal(COMPANY_URL, html("synthetic_generic_form")) == PortalType.GENERIC_FORM


def test_careers_list_with_an_email_box_is_unknown():
    # An email field without a file input is a job-alert box, not an application.
    assert detect_portal(COMPANY_URL, html("synthetic_careers_list")) == PortalType.UNKNOWN


# --- Fields -----------------------------------------------------------------------


def test_greenhouse_fields_labels_and_required():
    fields = parse_form_fields(html("synthetic_greenhouse"))

    assert [f.label for f in fields] == [
        "First Name", "Last Name", "Email", "Phone", "Resume/CV",
        "LinkedIn Profile", "What is your notice period?",
    ]
    assert by_label(fields, "First Name").required  # aria-required
    assert by_label(fields, "Email").autocomplete == "email"
    assert not by_label(fields, "Phone").required
    assert by_label(fields, "Resume/CV").kind == "file"
    notice = by_label(fields, "What is your notice period?")
    assert notice.kind == "select" and notice.required  # "*" in the label
    assert notice.options == ("Please select", "Immediate", "30 days", "60 days or more")


def test_hidden_inputs_and_buttons_are_not_fields():
    fields = parse_form_fields(html("synthetic_greenhouse"))
    assert all(f.name != "authenticity_token" for f in fields)
    assert all(f.kind != "submit" for f in fields)


def test_lever_wrapping_labels_and_radio_group():
    fields = parse_form_fields(html("synthetic_lever"))

    resume = by_label(fields, "Resume/CV")  # Lever's ✱ marker stripped
    assert resume.kind == "file" and resume.required
    assert by_label(fields, "LinkedIn URL").name == "urls[LinkedIn]"

    relocate = by_label(fields, "Are you willing to relocate to Bangalore?")
    assert relocate.kind == "radio"
    assert relocate.options == ("Yes", "No")
    assert relocate.required  # "*" in the legend
    assert sum(f.kind == "radio" for f in fields) == 1  # one group, not two inputs


def test_fields_remember_their_form():
    fields = parse_form_fields(html("synthetic_generic_form"))
    search = next(f for f in fields if f.name == "q")
    cv = next(f for f in fields if f.name == "cv")
    assert search.form == 0 and cv.form == 1


# --- Hard stops -------------------------------------------------------------------


def test_clean_greenhouse_and_lever_pages_have_no_hard_stops():
    # Both load an invisible CAPTCHA (runs on submit only) and the JD says
    # "Payments" / "PAN India": none of that is a stop.
    assert inspect_page(GREENHOUSE_URL, html("synthetic_greenhouse")).hard_stops == []
    assert inspect_page(LEVER_URL, html("synthetic_lever")).hard_stops == []
    assert inspect_page(COMPANY_URL, html("synthetic_generic_form")).hard_stops == []


def test_workday_login_page_stops():
    report = inspect_page(WORKDAY_URL, html("synthetic_workday_login"))

    assert report.portal == PortalType.WORKDAY
    assert any("Workday" in stop for stop in report.hard_stops)
    assert any("password field" in stop for stop in report.hard_stops)
    assert any("'create account'" in stop for stop in report.hard_stops)


def test_sensitive_otp_and_visible_captcha_stop():
    stops = inspect_page(COMPANY_URL, html("synthetic_sensitive_captcha")).hard_stops

    assert "asks for sensitive data (aadhaar): field 'Aadhaar Number'" in stops
    assert any(stop.startswith("OTP / email verification") for stop in stops)
    assert "CAPTCHA on the page" in stops


def test_unknown_wizard_stops():
    stops = inspect_page(COMPANY_URL, html("synthetic_wizard")).hard_stops
    assert stops == ["multi-step form we don't recognise (Next/Continue, no Submit)"]


# --- Real page: kmgus.com careers (job 455, saved 2026-10-15) ----------------------
# A WordPress careers list: each job's "Apply" link opens one shared modal
# with a Contact Form 7 resume form. Markers added by read_documents.

KMG_URL = "https://kmgus.com/careers/"


def test_real_careers_page_with_a_modal_form_stops():
    report = inspect_page(KMG_URL, html("generic_kmgus"))

    assert report.portal == PortalType.GENERIC_FORM
    # The resume form is in a closed modal; filling it needs a click first.
    assert report.hard_stops == ["application form is hidden (opens from a button or modal)"]


def test_real_page_resume_form_fields():
    fields = parse_form_fields(html("generic_kmgus"))
    resume = next(f for f in fields if f.name == "UploadResume")
    form = [f for f in fields if f.form == resume.form]

    assert [(f.name, f.kind, f.required) for f in form if f.kind != "checkbox"] == [
        ("Name", "text", True),
        ("Email", "email", True),
        ("mobile", "tel", True),
        ("UploadResume", "file", True),
        ("_wpcf7_ak_hp_textarea", "textarea", False),
    ]
    # A required marketing-consent box: the filler must not tick it on its own.
    assert next(f for f in form if f.name == "consent_email_communication").required


def test_real_page_honeypot_is_hidden_and_captcha_field_skipped():
    fields = parse_form_fields(html("generic_kmgus"))

    # Contact Form 7 / Akismet spam trap: filling it drops the application.
    honeypots = [f for f in fields if f.name == "_wpcf7_ak_hp_textarea"]
    assert honeypots and not any(f.visible for f in honeypots)
    # Visible contact form next to it stays visible.
    assert next(f for f in fields if f.name == "your-email").visible
    # Filled by the CAPTCHA script, never by us.
    assert all(f.name != "g-recaptcha-response" for f in fields)


def test_pages_saved_without_markers_count_as_visible():
    assert all(f.visible for f in parse_form_fields(html("synthetic_generic_form")))


# --- Opening a hidden form ---------------------------------------------------------


def test_opener_is_the_link_with_the_exact_job_title():
    selector = find_job_opener(html("generic_kmgus"), "Python Developer")
    assert selector == """a[onclick="Enquiry('Python Developer')"]"""


@pytest.mark.parametrize(
    "title",
    [
        "Python Developer (5 To 8 Years)",  # Naukri's title, not the site's: no fuzzy match
        "Python",
        "",
    ],
)
def test_no_opener_without_an_exact_title(title):
    assert find_job_opener(html("generic_kmgus"), title) is None


def test_opener_title_match_ignores_case_and_decodes_entities():
    # "Lead Engineer" must not pick "Lead Engineer (.Net)" either.
    page = html("generic_kmgus")
    assert find_job_opener(page, "full stack (.net & angular)") is not None
    assert find_job_opener(page, "Lead Engineer") == """a[onclick="Enquiry('Lead Engineer')"]"""


def test_opener_must_stay_on_the_page_and_be_unique():
    leaves = """<a href="https://evil.example/x" onclick="Enquiry('Dev')">Apply</a>"""
    assert find_job_opener(leaves, "Dev") is None

    two = """<a href="#" onclick="Enquiry('Dev')">A</a><button onclick="openForm('Dev')">B</button>"""
    assert find_job_opener(two, "Dev") is None

    # Double quotes inside the onclick are escaped in the selector.
    button = """<button type="button" onclick='openForm("Dev", 3)'>Apply</button>"""
    assert find_job_opener(button, "Dev") == r"""button[onclick="openForm(\"Dev\", 3)"]"""


def test_real_page_after_opening_the_form_has_no_hard_stops():
    # The same page after one click on Enquiry('Python Developer') (saved live).
    page = html("generic_kmgus_form_open")
    report = inspect_page(KMG_URL, page)

    assert report.portal == PortalType.GENERIC_FORM
    assert report.hard_stops == []
    resume_form = next(f for f in report.fields if f.name == "UploadResume").form
    in_form = [f for f in report.fields if f.form == resume_form]
    assert [f.name for f in in_form if f.visible and f.kind != "checkbox"] == [
        "Name", "Email", "mobile", "UploadResume",
    ]
    # The honeypot stays hidden after the modal opens.
    assert not next(f for f in in_form if f.name == "_wpcf7_ak_hp_textarea").visible
    # The click told the site which job: its hidden title field holds it.
    assert 'value="Python Developer" type="hidden" name="ServiceName"' in page


# --- Real page: Greenhouse job board embedded by Tower Research (job 3, 2026-10-15) ---
# The new React board: Yes/No questions are searchable dropdowns, and a PEP
# declaration mentions "World Bank". validityToken redacted.

GH_FRAME_URL = "https://job-boards.greenhouse.io/embed/job_app?for=towerresearchcapital"


def test_real_greenhouse_board_has_no_hard_stop():
    # "World Bank" in a PEP question is not a bank-details field; reCAPTCHA is invisible.
    report = inspect_page(GH_FRAME_URL, html("greenhouse_tower_frame"))
    assert report.portal == PortalType.GREENHOUSE
    assert report.hard_stops == []


def test_real_greenhouse_dropdowns_are_comboboxes():
    fields = {f.id: f for f in parse_form_fields(html("greenhouse_tower_frame")) if f.id}
    assert fields["country"].kind == "combobox"
    assert fields["question_54153733"].kind == "combobox"  # the PEP Yes/No question
    assert fields["question_54153730"].kind == "text"  # LinkedIn stays a text field
    assert fields["resume"].kind == "file"


# --- The job's own apply page (find_job_page_link) -----------------------------------

ZAAX_LIST = "https://www.zaax.com/job-openings/#openings"


def test_zaax_list_links_python_developer_to_the_shared_form():
    html = (FIXTURES / "generic_zaax_job_openings.html").read_text(encoding="utf-8")
    assert find_job_page_link(html, ZAAX_LIST, "Python  developer") == "https://www.zaax.com/submit-resume/"
    assert find_job_page_link(html, ZAAX_LIST, "Go Developer") is None


ROW = '<h3>{title}</h3><p>About the role</p><a href="{href}">{text}</a>'


@pytest.mark.parametrize(
    ("html", "why"),
    [
        (ROW.format(title="Python Developer", href="https://jobs.other.com/apply", text="Apply"), "other host"),
        (ROW.format(title="Python Developer", href="#openings", text="Apply"), "same page"),
        (ROW.format(title="Python Developer", href="javascript:open()", text="Apply"), "script"),
        (ROW.format(title="Python Developer", href="/team", text="Meet the team"), "not an apply link"),
        (ROW.format(title="Python Developer", href="/a", text="Apply") * 2, "title twice"),
        (ROW.format(title="Senior Python Developer", href="/a", text="Apply"), "not the exact title"),
        ("<h3>Python Developer</h3><h3>Java Developer</h3><a href='/java'>Apply</a>", "link of the next job"),
    ],
)
def test_job_page_link_is_strict(html, why):
    assert find_job_page_link(html, ZAAX_LIST, "Python Developer") is None, why
