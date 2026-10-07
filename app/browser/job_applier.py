"""Apply to one Naukri job in a real browser.

Decisions only; the clicks live in apply_page.NaukriApplyPage. Safety rules:
- only the on-Naukri "Apply" is clicked; company-site / unknown → NEEDS_MANUAL;
- every question is answered from answers.yaml by deterministic rules; the
  first question without a sure answer stops the run (NEEDS_MANUAL) before
  anything is typed or sent for it;
- APPLIED only when the page confirms it; otherwise an error is raised, which
  ApplyService records as FAILED for a human to check.

Naukri's chatbot asks one question at a time, so answers given before an
unknown question were already sent to it. The application itself is not
submitted in that case.
"""

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol

import structlog

from app.browser.apply_button import ApplyButtonType, classify_apply_button
from app.browser.apply_page import ApplyPage, NaukriApplyPage, NextStep
from app.browser.apply_questions import map_question
from app.browser.naukri_browser import NaukriBrowser
from app.browser.session_store import SessionStateError
from app.config import settings
from app.models.application_answers import ApplicationAnswers
from app.models.apply_result import ApplierResult, ApplyOutcome
from app.models.job import Job

logger = structlog.get_logger(__name__)

ARTIFACTS_DIR = Path("artifacts/apply")

LOGIN_HINT = "Run: uv run python -m scripts.naukri_login"

# Human-like pause between actions, in seconds.
MIN_PAUSE_S = 1.0
MAX_PAUSE_S = 3.0

# A real questionnaire is a handful of questions; more means we are looping.
MAX_QUESTIONS = 15


class SessionExpiredError(Exception):
    """The saved Naukri login is missing or no longer valid."""


class ApplyNotConfirmedError(Exception):
    """We clicked, but the page never confirmed the application."""


class JobApplier(Protocol):
    async def apply(self, job_id: int, job: Job, answers: ApplicationAnswers) -> ApplierResult:
        """Apply in the browser. Returns APPLIED, NEEDS_MANUAL or ALREADY_APPLIED;
        raises on unexpected errors."""
        ...


# job_id -> an open page; closed (browser shut) when the block ends.
PageOpener = Callable[[int], AbstractAsyncContextManager[ApplyPage]]


@asynccontextmanager
async def open_naukri_page(job_id: int) -> AsyncIterator[ApplyPage]:
    """A logged-in, HEADED browser for one apply.

    Headed on purpose (BROWSER_HEADLESS is ignored): a live apply is watched
    by a human, and headless browsers are flagged as bots more often.
    """
    run_dir = ARTIFACTS_DIR / str(job_id) / datetime.now().strftime("%Y%m%d-%H%M%S")
    browser = NaukriBrowser(headless=False, timeout_ms=settings.BROWSER_TIMEOUT_MS, logged_in=True)
    try:
        try:
            await browser.start()
        except SessionStateError as error:
            raise SessionExpiredError(f"session expired or missing: {error}") from None
        logger.info("apply_artifacts_dir", job_id=job_id, path=str(run_dir))
        yield NaukriApplyPage(browser, run_dir, random.Random())
    finally:
        await browser.close()


class NaukriJobApplier:

    def __init__(
        self,
        open_page: PageOpener = open_naukri_page,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ):
        # Injected so tests run with a fake page and no real waiting.
        self.open_page = open_page
        self.sleep = sleep
        self.rng = rng or random.Random()

    async def apply(self, job_id: int, job: Job, answers: ApplicationAnswers) -> ApplierResult:
        async with self.open_page(job_id) as page:
            try:
                return await self._apply_on(page, job_id, job, answers)
            except Exception:
                # The last screen is what a human needs to see to fix it.
                await page.snapshot("error")
                raise

    async def _apply_on(
        self, page: ApplyPage, job_id: int, job: Job, answers: ApplicationAnswers
    ) -> ApplierResult:
        await page.open(job.url)
        if not await page.is_logged_in():
            raise SessionExpiredError(f"session expired: Naukri shows no login. {LOGIN_HINT}")
        await page.snapshot("job_page")

        button = classify_apply_button(await page.apply_buttons())
        logger.info("apply_button", job_id=job_id, button=button.value)
        if button == ApplyButtonType.ALREADY_APPLIED:
            return ApplierResult(outcome=ApplyOutcome.ALREADY_APPLIED, reason="Naukri shows already applied")
        if button == ApplyButtonType.COMPANY_SITE:
            return _manual("apply on the company site")
        if button != ApplyButtonType.NAUKRI_APPLY:
            return _manual("no known apply button on the page")

        await self._pause()
        await page.click_apply()

        for _ in range(MAX_QUESTIONS + 1):
            step = await page.wait_for_next_step()
            await page.snapshot(step.value)

            if step == NextStep.SUCCESS:
                logger.info("apply_confirmed", job_id=job_id)
                return ApplierResult(outcome=ApplyOutcome.APPLIED)
            if step == NextStep.NOTHING:
                raise ApplyNotConfirmedError("no question and no 'applied' confirmation after clicking")

            question = await page.read_question()
            answer = map_question(question, answers)
            if answer is None:
                # Stop before typing anything for it: a guess could reach a recruiter.
                return _manual(f"unknown question: {question.text!r}")

            logger.info("apply_question_answered", job_id=job_id, question=question.text)
            await self._pause()
            if question.options:
                await page.choose_option(answer)
            else:
                await page.type_answer(answer)
            await self._pause()
            await page.send_answer()

        raise ApplyNotConfirmedError(f"more than {MAX_QUESTIONS} questions; stopped")

    async def _pause(self) -> None:
        await self.sleep(self.rng.uniform(MIN_PAUSE_S, MAX_PAUSE_S))


def _manual(reason: str) -> ApplierResult:
    return ApplierResult(outcome=ApplyOutcome.NEEDS_MANUAL, reason=reason)
