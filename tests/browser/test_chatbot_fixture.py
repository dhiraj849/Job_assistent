"""Chatbot selectors on the saved live drawer, in a real (headless) Chromium.

CSS selectors need a browser to be checked for real; the network is blocked,
so nothing leaves the test. Skipped when Playwright's Chromium is missing.
"""

import asyncio
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.browser import naukri_selectors as selectors
from app.browser.apply_page import NaukriApplyPage
from app.browser.apply_questions import map_question
from app.models.application_answers import ApplicationAnswers

FIXTURES = Path(__file__).parent.parent / "fixtures" / "naukri"
CHATBOT = FIXTURES / "chatbot.html"  # job 1076: checkbox question
CHATBOT_RADIO = FIXTURES / "chatbot_radio.html"  # job 7: radio question
QUESTION = "Which of these locations are you willing to relocate to?"
CITIES = ["Bengaluru", "Gurugram", "Hyderabad", "Noida", "Pune"]


async def _on_fixture(check, fixture: Path = CHATBOT):
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except PlaywrightError as error:
            pytest.skip(f"no Chromium for Playwright: {error}")
        page = await browser.new_page()
        await page.route("**/*", lambda route: route.abort())
        await page.set_content(fixture.read_text(encoding="utf-8"))
        try:
            return await check(page)
        finally:
            await browser.close()


def test_every_chatbot_selector_on_the_live_drawer():
    async def counts(page):
        names = ["CHATBOT", "CHATBOT_BOT_MESSAGE", "CHATBOT_TEXT_INPUT", "CHATBOT_RADIO_LABEL",
                 "CHATBOT_CHECKBOX", "CHATBOT_CHECKBOX_LABEL", "CHATBOT_SEND"]
        found = {name: await page.locator(getattr(selectors, name)).count() for name in names}
        send = (await page.locator(selectors.CHATBOT_SEND).last.inner_text()).strip()
        return found, send

    found, send = asyncio.run(_on_fixture(counts))

    assert found == {
        "CHATBOT": 1,
        "CHATBOT_BOT_MESSAGE": 2,  # greeting + the open question
        "CHATBOT_TEXT_INPUT": 1,
        "CHATBOT_RADIO_LABEL": 0,  # a checkbox question
        "CHATBOT_CHECKBOX": 5,
        "CHATBOT_CHECKBOX_LABEL": 5,
        "CHATBOT_SEND": 1,
    }
    assert send == "Save"


def _read_question(tmp_path, fixture: Path = CHATBOT):
    async def read(page):
        apply_page = NaukriApplyPage(SimpleNamespace(page=page), tmp_path, random.Random(0))
        return await apply_page.read_question()

    return asyncio.run(_on_fixture(read, fixture))


def test_read_question_gives_the_open_question_and_its_options(tmp_path):
    question = _read_question(tmp_path)

    assert question.text == QUESTION
    assert question.options == CITIES
    assert question.multi_select


ANSWERS = ApplicationAnswers(
    notice_period_days=30, current_ctc_lpa=8, expected_ctc_lpa=12,
    current_location="Noida", willing_to_relocate=True, total_experience_years=3,
)


def test_multi_select_question_is_left_for_me(tmp_path):
    # The applier then stops with needs_manual: it never ticks checkboxes.
    assert map_question(_read_question(tmp_path), ANSWERS) is None


def test_radio_question_is_read_answered_and_picked(tmp_path):
    question = _read_question(tmp_path, CHATBOT_RADIO)
    assert (question.text, question.options, question.multi_select) == (
        "What is your current location", ["Noida / Delhi / Gurgaon", "None of above"], False,
    )
    answer = map_question(question, ANSWERS)
    assert answer == "Noida / Delhi / Gurgaon"

    async def choose(page):
        apply_page = NaukriApplyPage(SimpleNamespace(page=page), tmp_path, random.Random(0))
        await apply_page.choose_option(answer)
        return await page.locator("input[type='radio']:checked").get_attribute("value")

    # choose_option clicks the label; its radio is the one checked. Nothing is sent.
    assert asyncio.run(_on_fixture(choose, CHATBOT_RADIO)) == "Noida / Delhi / Gurgaon"
