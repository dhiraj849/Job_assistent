"""NaukriJobApplier decisions, with a fake page: no browser, no network."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.browser.apply_button import ApplyButton
from app.browser.apply_page import NextStep
from app.browser.apply_questions import Question
from app.browser.company_site_page import FrameDocument
from app.browser.job_applier import ApplyNotConfirmedError, NaukriJobApplier, SessionExpiredError
from app.models.application_answers import ApplicationAnswers
from app.models.apply_result import ApplyOutcome
from app.models.job import Job

JOB = Job(title="Python Dev", company="Acme", location="Noida", description="", url="https://naukri/x/7")
ANSWERS = ApplicationAnswers(
    notice_period_days=30,
    current_ctc_lpa=10,
    expected_ctc_lpa=14,
    current_location="Noida",
    willing_to_relocate=True,
    total_experience_years=4,
)
APPLY = [ApplyButton("", "Apply")]
COMPANY = [ApplyButton("company-site-button", "Apply on company site")]
SITES = Path(__file__).parent.parent / "fixtures" / "company_sites"


def site(name: str, url: str, frame: str = "page") -> FrameDocument:
    return FrameDocument(frame, url, (SITES / f"{name}.html").read_text(encoding="utf-8"))


class FakePage:
    """Plays back a scripted Naukri page and records every action."""

    def __init__(self, buttons, steps=(), questions=(), logged_in=True, company=()):
        self.buttons = list(buttons)
        # One list of documents per read of the company site (before / after opening its form).
        self.company = list(company)
        self.steps = list(steps)
        self.questions = list(questions)
        self.logged_in = logged_in
        self.actions: list[str] = []
        self.snapshots: list[str] = []

    async def open(self, url):
        self.actions.append(f"open {url}")

    async def is_logged_in(self):
        return self.logged_in

    async def apply_buttons(self):
        return self.buttons

    async def click_apply(self):
        self.actions.append("click_apply")

    async def wait_for_next_step(self):
        return self.steps.pop(0) if self.steps else NextStep.NOTHING

    async def read_question(self):
        return self.questions.pop(0)

    async def choose_option(self, option):
        self.actions.append(f"choose {option}")

    async def type_answer(self, text):
        self.actions.append(f"type {text}")

    async def send_answer(self):
        self.actions.append("send")

    async def snapshot(self, step):
        self.snapshots.append(step)

    async def open_company_site(self):
        self.actions.append("open_company_site")

    async def company_documents(self):
        return self.company.pop(0) if len(self.company) > 1 else self.company[0]

    async def open_company_url(self, url):
        self.actions.append(f"open_company_url {url}")

    async def open_company_form(self, selector):
        self.actions.append(f"open_company_form {selector}")

    async def open_company_job_page(self, url):
        self.actions.append(f"open_company_job_page {url}")


def run(page: FakePage, job: Job = JOB, on_click=None, company_site_url=None):
    @asynccontextmanager
    async def open_page(job_id):
        yield page

    async def no_sleep(seconds):
        pass

    applier = NaukriJobApplier(open_page=open_page, sleep=no_sleep)
    return asyncio.run(
        applier.apply(7, job, ANSWERS, on_company_site_click=on_click, company_site_url=company_site_url)
    )


# --- Company site: the page is only read; the fill session is mine -----------------

KMG = "https://kmgus.com/careers/"
KMG_JOB = JOB.model_copy(update={"title": "Python Developer"})


def test_company_site_with_a_modal_form_is_ready_for_me():
    page = FakePage(COMPANY, company=[[site("generic_kmgus", KMG)], [site("generic_kmgus_form_open", KMG)]])
    clicks = []

    async def on_click():
        clicks.append(list(page.actions))  # what had happened before the hook ran

    result = run(page, KMG_JOB, on_click)

    assert result.outcome == ApplyOutcome.READY_FOR_YOU
    assert result.company_site.url == KMG
    assert result.company_site.portal == "generic_form"
    assert result.company_site.human_steps == []  # its reCAPTCHA is invisible
    assert "scripts.apply_company_site 7" in result.reason
    # The click is recorded BEFORE Naukri's button is clicked.
    assert clicks == [[f"open {JOB.url}"]]
    assert page.actions[1:] == [
        "open_company_site",
        """open_company_form a[onclick="Enquiry('Python Developer')"]""",
    ]
    assert page.snapshots == ["job_page", "company_site", "company_form"]
    assert "click_apply" not in page.actions


def test_title_not_on_the_careers_list_needs_manual():
    # Naukri's title differs from the site's: no fuzzy match, the form stays closed.
    page = FakePage(COMPANY, company=[[site("generic_kmgus", KMG)]])
    result = run(page, JOB)

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert "application form is hidden" in result.reason and KMG in result.reason
    assert not any(action.startswith("open_company_form") for action in page.actions)


def test_login_site_needs_manual_with_its_url():
    url = "https://acme.wd3.myworkdayjobs.com/careers/login"
    result = run(FakePage(COMPANY, company=[[site("synthetic_workday_login", url)]]))

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert result.company_site.portal == "workday"
    assert url in result.reason


def test_sensitive_field_blocks_even_with_captcha():
    url = "https://careers.acme.example/apply"
    result = run(FakePage(COMPANY, company=[[site("synthetic_sensitive_captcha", url)]]))

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert "aadhaar" in result.reason
    assert result.company_site.human_steps == ["captcha", "otp"]


def test_visible_captcha_is_a_step_for_me_not_a_stop():
    html = (SITES / "synthetic_generic_form.html").read_text(encoding="utf-8").replace(
        "</form></main>", '<div class="g-recaptcha" data-sitekey="k"></div></form></main>'
    )
    url = "https://careers.acme.example/apply"
    result = run(FakePage(COMPANY, company=[[FrameDocument("page", url, html)]]))

    assert result.outcome == ApplyOutcome.READY_FOR_YOU
    assert result.company_site.human_steps == ["captcha"]
    assert "you will do: captcha" in result.reason


def test_form_in_an_ats_iframe_keeps_the_page_url():
    frame_url = "https://boards.greenhouse.io/embed/job_app?for=acme&token=123"
    docs = [
        site("synthetic_embedded_greenhouse", "https://acme.example/join"),
        site("synthetic_greenhouse", frame_url, "frame_1"),
    ]
    result = run(FakePage(COMPANY, company=[docs]))

    assert result.outcome == ApplyOutcome.READY_FOR_YOU
    assert (result.company_site.url, result.company_site.portal) == ("https://acme.example/join", "greenhouse")


def test_already_applied():
    page = FakePage([ApplyButton("", "Applied")])
    assert run(page).outcome == ApplyOutcome.ALREADY_APPLIED
    assert "click_apply" not in page.actions


def test_unknown_button_needs_manual():
    page = FakePage([ApplyButton("", "Save")])
    assert run(page).outcome == ApplyOutcome.NEEDS_MANUAL
    assert "click_apply" not in page.actions


def test_session_expired_raises_before_anything():
    page = FakePage(APPLY, logged_in=False)
    with pytest.raises(SessionExpiredError, match="session expired"):
        run(page)
    assert page.actions == [f"open {JOB.url}"]


def test_no_questions_confirmed_is_applied():
    page = FakePage(APPLY, steps=[NextStep.SUCCESS])
    assert run(page).outcome == ApplyOutcome.APPLIED
    assert page.snapshots == ["job_page", "success"]


def test_questions_are_answered_then_confirmed():
    page = FakePage(
        APPLY,
        steps=[NextStep.QUESTION, NextStep.QUESTION, NextStep.SUCCESS],
        questions=[
            Question("What is your notice period?", ["15 Days or less", "1 Month"]),
            Question("What is your expected CTC?"),
        ],
    )
    result = run(page)

    assert result.outcome == ApplyOutcome.APPLIED
    assert page.actions[1:] == ["click_apply", "choose 1 Month", "send", "type 14 LPA", "send"]


def test_unknown_question_stops_without_answering_or_sending():
    page = FakePage(
        APPLY,
        steps=[NextStep.QUESTION, NextStep.SUCCESS],
        questions=[Question("Why do you want to join us?")],
    )
    result = run(page)

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert "Why do you want to join us?" in result.reason
    assert "send" not in page.actions
    assert not any(a.startswith(("type", "choose")) for a in page.actions)


def test_unknown_question_after_known_one_sends_only_the_known_answer():
    page = FakePage(
        APPLY,
        steps=[NextStep.QUESTION, NextStep.QUESTION],
        questions=[Question("What is your expected CTC?"), Question("Describe your best project")],
    )
    result = run(page)

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert page.actions.count("send") == 1


def test_no_confirmation_raises_instead_of_applied():
    page = FakePage(APPLY, steps=[NextStep.NOTHING])
    with pytest.raises(ApplyNotConfirmedError):
        run(page)
    assert page.snapshots[-1] == "error"


def test_endless_questions_raise():
    question = Question("What is your current location?")
    page = FakePage(APPLY, steps=[NextStep.QUESTION] * 50, questions=[question] * 50)
    with pytest.raises(ApplyNotConfirmedError, match="questions"):
        run(page)


ZAAX = "https://www.zaax.com/job-openings/#openings"
ZAAX_FORM = "https://www.zaax.com/submit-resume/"


def test_careers_list_follows_the_jobs_own_apply_page():
    """Job 1065: the list has no form; "Apply Now" links to one shared form page."""
    page = FakePage(
        COMPANY,
        company=[[site("generic_zaax_job_openings", ZAAX)], [site("generic_zaax_submit_resume", ZAAX_FORM)]],
    )

    result = run(page, KMG_JOB)

    assert result.outcome == ApplyOutcome.READY_FOR_YOU
    assert result.company_site.url == ZAAX_FORM  # the fill session opens the form page directly
    assert result.company_site.portal == "generic_form"
    assert page.actions[1:] == ["open_company_site", f"open_company_job_page {ZAAX_FORM}"]
    assert page.snapshots == ["job_page", "company_site", "company_job_page"]


def test_careers_list_without_this_job_stays_manual():
    page = FakePage(COMPANY, company=[[site("generic_zaax_job_openings", ZAAX)]])

    result = run(page, JOB.model_copy(update={"title": "Go Developer"}))

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert not any(a.startswith("open_company_job_page") for a in page.actions)


def test_known_company_url_is_checked_without_naukri():
    # Naukri would say "Applied" (our earlier click): it is never even opened.
    page = FakePage([ApplyButton("", "Applied")], company=[[site("generic_kmgus", KMG)], [site("generic_kmgus_form_open", KMG)]])
    result = run(page, KMG_JOB, company_site_url=KMG)

    assert result.outcome == ApplyOutcome.READY_FOR_YOU
    assert page.actions[0] == f"open_company_url {KMG}"
    assert f"open {JOB.url}" not in page.actions and "open_company_site" not in page.actions


def test_real_greenhouse_board_in_an_iframe_is_ready_for_me():
    frame_url = "https://job-boards.greenhouse.io/embed/job_app?for=towerresearchcapital"
    docs = [
        FrameDocument("page", "https://tower-research.com/open-positions/?gh_jid=6629676", "<html></html>"),
        site("greenhouse_tower_frame", frame_url, "frame_2"),
    ]
    result = run(FakePage(COMPANY, company=[docs]))

    assert result.outcome == ApplyOutcome.READY_FOR_YOU
    # The page URL, not the iframe's (its token expires).
    assert (result.company_site.url, result.company_site.portal) == (
        "https://tower-research.com/open-positions/?gh_jid=6629676", "greenhouse"
    )


def test_real_page_implements_every_apply_page_method():
    # The fake page above can hide a method missing on the real one (seen
    # 2026-10-15: open_company_url ended up only in the Protocol).
    from app.browser.apply_page import ApplyPage, NaukriApplyPage

    wanted = {name for name in vars(ApplyPage) if not name.startswith("_")}
    assert wanted <= set(dir(NaukriApplyPage))
    assert wanted <= set(dir(FakePage))
