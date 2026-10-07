"""Recognise which apply button a Naukri job page shows.

UNVERIFIED selectors: taken from common Naukri markup, not yet checked on a
live page. scripts/inspect_apply_flow.py saves the HTML so they can be fixed.
"""

from enum import StrEnum

# Buttons in the job header that can hold the apply action.
APPLY_BUTTON_CANDIDATES = (
    "#apply-button, #company-site-button, #already-applied, "
    "button:has-text('Apply'), button:has-text('Applied')"
)


class ApplyButtonType(StrEnum):
    NAUKRI_APPLY = "naukri_apply"
    COMPANY_SITE = "company_site"
    ALREADY_APPLIED = "already_applied"
    UNKNOWN = "unknown"


def classify_apply_button(texts: list[str]) -> ApplyButtonType:
    """Decide the button type from the visible button texts.

    Order matters: "Applied" and "Apply on company site" both contain "apply",
    so the more specific texts are checked first.
    """
    normalized = [" ".join(text.lower().split()) for text in texts]

    if any(text == "applied" or text.startswith("already applied") for text in normalized):
        return ApplyButtonType.ALREADY_APPLIED
    if any("company site" in text for text in normalized):
        return ApplyButtonType.COMPANY_SITE
    if any(text == "apply" or text == "apply now" for text in normalized):
        return ApplyButtonType.NAUKRI_APPLY
    return ApplyButtonType.UNKNOWN
