"""NaukriJobApplier decisions, with a fake page: no browser, no network."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.browser.apply_button import ApplyButton
from app.browser.apply_page import NextStep
from app.browser.apply_questions import Question
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


class FakePage:
    """Plays back a scripted Naukri page and records every action."""

    def __init__(self, buttons, steps=(), questions=(), logged_in=True):
        self.buttons = list(buttons)
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


def run(page: FakePage):
    @asynccontextmanager
    async def open_page(job_id):
        yield page

    async def no_sleep(seconds):
        pass

    return asyncio.run(NaukriJobApplier(open_page=open_page, sleep=no_sleep).apply(7, JOB, ANSWERS))


def test_company_site_needs_manual_and_clicks_nothing():
    page = FakePage([ApplyButton("company-site-button", "Apply on company site")])
    result = run(page)

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert "company site" in result.reason
    assert "click_apply" not in page.actions


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
