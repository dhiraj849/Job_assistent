"""Recognise which apply button a Naukri job page shows.

Selectors live in naukri_selectors.py (with their verification status).
"""

from enum import StrEnum
from typing import NamedTuple

from app.browser.naukri_selectors import APPLY_BUTTON_IDS, APPLY_BUTTONS


class ApplyButtonType(StrEnum):
    NAUKRI_APPLY = "naukri_apply"
    COMPANY_SITE = "company_site"
    ALREADY_APPLIED = "already_applied"
    UNKNOWN = "unknown"


class ApplyButton(NamedTuple):
    id: str
    text: str


# Most specific first: "Applied" and "Apply on company site" both contain
# "apply", so a page showing several buttons resolves to the safest type.
_PRIORITY = (
    ApplyButtonType.ALREADY_APPLIED,
    ApplyButtonType.COMPANY_SITE,
    ApplyButtonType.NAUKRI_APPLY,
)


def _type_from_text(text: str) -> ApplyButtonType:
    text = " ".join(text.lower().split())
    if text == "applied" or text.startswith("already applied"):
        return ApplyButtonType.ALREADY_APPLIED
    if "company site" in text:
        return ApplyButtonType.COMPANY_SITE
    if text in ("apply", "apply now"):
        return ApplyButtonType.NAUKRI_APPLY
    return ApplyButtonType.UNKNOWN


def classify_apply_button(buttons: list[ApplyButton]) -> ApplyButtonType:
    """Decide the button type: a known element id wins, else the exact text."""
    found = set()
    for button in buttons:
        by_id = APPLY_BUTTON_IDS.get(button.id)
        found.add(ApplyButtonType(by_id) if by_id else _type_from_text(button.text))

    for button_type in _PRIORITY:
        if button_type in found:
            return button_type
    return ApplyButtonType.UNKNOWN


async def read_apply_buttons(page) -> list[ApplyButton]:
    """(id, visible text) of every candidate apply button on a Playwright page."""
    pairs = await page.locator(APPLY_BUTTONS).evaluate_all(
        "els => els.map(e => [e.id || '', (e.innerText || '').trim()])"
    )
    return [ApplyButton(id_, text) for id_, text in pairs]
