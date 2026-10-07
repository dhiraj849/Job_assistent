"""The browser side of applying, behind a small interface.

NaukriJobApplier only talks to an ApplyPage, so its decisions (stop, answer,
confirm) are tested with a fake page. NaukriApplyPage is the thin Playwright
version; it holds no decisions, only clicks, reads and waits.
"""

import random
import re
import time
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import structlog
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from app.browser.apply_button import (
    ApplyButton,
    ApplyButtonType,
    classify_apply_button,
    read_apply_buttons,
)
from app.browser.apply_questions import Question
from app.browser.naukri_browser import NaukriBrowser
from app.browser.naukri_selectors import (
    APPLY_BUTTONS,
    APPLY_SUCCESS,
    CHATBOT_BOT_MESSAGE,
    CHATBOT_CHECKBOX,
    CHATBOT_RADIO_LABEL,
    CHATBOT_SEND,
    CHATBOT_TEXT_INPUT,
)

logger = structlog.get_logger(__name__)

# Exact text, so "Applied" / "Apply on company site" can never be clicked.
NAUKRI_APPLY_TEXT = re.compile(r"^\s*apply( now)?\s*$", re.IGNORECASE)

# How long to wait for the page to react after a click / an answer.
NEXT_STEP_TIMEOUT_S = 15
POLL_INTERVAL_MS = 500


class NextStep(StrEnum):
    SUCCESS = "success"
    QUESTION = "question"
    NOTHING = "nothing"  # neither a question nor a confirmation appeared


class ApplyPage(Protocol):
    async def open(self, url: str) -> None: ...
    async def is_logged_in(self) -> bool: ...
    async def apply_buttons(self) -> list[ApplyButton]: ...
    async def click_apply(self) -> None: ...
    async def wait_for_next_step(self) -> NextStep: ...
    async def read_question(self) -> Question: ...
    async def choose_option(self, option: str) -> None: ...
    async def type_answer(self, text: str) -> None: ...
    async def send_answer(self) -> None: ...
    async def snapshot(self, step: str) -> None: ...


class NaukriApplyPage:
    """ApplyPage on a real, logged-in Naukri browser."""

    def __init__(self, browser: NaukriBrowser, artifacts_dir: Path, rng: random.Random):
        self.browser = browser
        self.artifacts_dir = artifacts_dir
        self.rng = rng
        self.steps = 0
        # Bot messages already answered; a higher count means a new question.
        self.seen_messages = 0

    @property
    def page(self) -> Page:
        return self.browser.page

    async def open(self, url: str) -> None:
        await self.page.goto(url, wait_until="load")
        # Let client-side rendering finish before we look at the buttons.
        await self.page.wait_for_timeout(3000)

    async def is_logged_in(self) -> bool:
        return await self.browser.is_logged_in()

    async def apply_buttons(self) -> list[ApplyButton]:
        return await read_apply_buttons(self.page)

    async def click_apply(self) -> None:
        await self.page.locator(APPLY_BUTTONS).filter(has_text=NAUKRI_APPLY_TEXT).first.click()

    async def wait_for_next_step(self) -> NextStep:
        deadline = time.monotonic() + NEXT_STEP_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                if await self._is_success():
                    return NextStep.SUCCESS
                if await self.page.locator(CHATBOT_BOT_MESSAGE).count() > self.seen_messages:
                    return NextStep.QUESTION
            except PlaywrightError:
                # Success redirects to a new page; a read during the
                # navigation fails. Not an answer either way: poll again.
                pass
            await self.page.wait_for_timeout(POLL_INTERVAL_MS)
        return NextStep.NOTHING

    async def _is_success(self) -> bool:
        if await self.page.locator(APPLY_SUCCESS).count():
            return True
        # The header button turning into "Applied" also confirms it.
        buttons = await self.apply_buttons()
        return classify_apply_button(buttons) == ApplyButtonType.ALREADY_APPLIED

    async def read_question(self) -> Question:
        messages = self.page.locator(CHATBOT_BOT_MESSAGE)
        self.seen_messages = await messages.count()
        text = (await messages.last.inner_text()).strip()
        options = [
            label.strip()
            for label in await self.page.locator(CHATBOT_RADIO_LABEL).all_inner_texts()
            if label.strip()
        ]
        multi_select = await self.page.locator(CHATBOT_CHECKBOX).count() > 0
        return Question(text=text, options=options, multi_select=multi_select)

    async def choose_option(self, option: str) -> None:
        exact = re.compile(rf"^\s*{re.escape(option)}\s*$")
        await self.page.locator(CHATBOT_RADIO_LABEL).filter(has_text=exact).first.click()

    async def type_answer(self, text: str) -> None:
        field = self.page.locator(CHATBOT_TEXT_INPUT).last
        await field.click()
        # Per-key delay, like a person typing.
        await field.press_sequentially(text, delay=self.rng.uniform(80, 200))

    async def send_answer(self) -> None:
        await self.page.locator(CHATBOT_SEND).last.click()

    async def snapshot(self, step: str) -> None:
        """Save HTML + screenshot of this step. Never fails the apply."""
        self.steps += 1
        base = self.artifacts_dir / f"{self.steps:02d}_{step}"
        try:
            self.artifacts_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            base.with_suffix(".html").write_text(await self.page.content(), encoding="utf-8")
            await self.page.screenshot(path=base.with_suffix(".png"), full_page=True)
        except Exception:
            logger.warning("apply_snapshot_failed", step=step, exc_info=True)
