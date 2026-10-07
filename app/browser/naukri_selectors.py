"""Every CSS selector the apply flow uses, in one place.

Naukri changes its markup without notice; when a live apply breaks, this is
the only file to fix. Each selector says where it was checked:

- VERIFIED <date>: seen in a saved live page (tests/fixtures/naukri/ or a login run).
- NOT VERIFIED: from public Naukri markup, no live sample yet. The applier is
  written so a wrong selector here makes it stop (NEEDS_MANUAL or an error),
  never report a false APPLIED. Verify with scripts/inspect_apply_flow.py.
"""

# --- Session -----------------------------------------------------------------

# Only shown to a logged-in user (header avatar / profile link).
# VERIFIED 2026-09-24 (live login).
LOGGED_IN_MARKER = ".nI-gNb-drawer__icon, .nI-gNb-icon-img, a[href*='/mnjuser/profile']"

# --- Apply button in the job header ---------------------------------------------

# Element id -> button type value (see apply_button.ApplyButtonType).
# Ids are more stable than texts, so they are checked first.
APPLY_BUTTON_IDS = {
    # VERIFIED 2026-09-24 (tests/fixtures/naukri/company_site.html).
    "company-site-button": "company_site",
    # VERIFIED 2026-10-07 (tests/fixtures/naukri/naukri_apply.html).
    "apply-button": "naukri_apply",
    # NOT VERIFIED.
    "already-applied": "already_applied",
}

# All header buttons that can hold the apply action. The text fallbacks catch
# a renamed id; classify_apply_button still decides by exact text.
APPLY_BUTTONS = ", ".join(
    [f"#{button_id}" for button_id in APPLY_BUTTON_IDS]
    + ["button:has-text('Apply')", "button:has-text('Applied')"]
)

# --- After clicking Apply ----------------------------------------------------------

# Naukri's "chatbot" drawer that asks screening questions one at a time.
# NOT VERIFIED (all chatbot selectors). Hint: job pages have an empty
# <div id="chatbot-container"> (seen 2026-10-07); the drawer likely renders there.
CHATBOT = ".chatbot_DrawerContentWrapper"
CHATBOT_BOT_MESSAGE = f"{CHATBOT} .botMsg"
CHATBOT_TEXT_INPUT = f"{CHATBOT} [contenteditable='true']"
CHATBOT_RADIO_LABEL = f"{CHATBOT} .ssrc__radio-btn-container label"
CHATBOT_CHECKBOX = f"{CHATBOT} input[type='checkbox']"
CHATBOT_SEND = f"{CHATBOT} .sendMsg"

# Confirmation that the application went through: Naukri redirects to an
# "apply confirmation page" headed "Applied to <job title>".
# VERIFIED 2026-10-07 (tests/fixtures/naukri/apply_success.html).
APPLY_SUCCESS_CONTAINER = ".acp-header-container .job-title-text"
APPLY_SUCCESS_TEXT = "Applied to"
APPLY_SUCCESS = f"{APPLY_SUCCESS_CONTAINER}:has-text('{APPLY_SUCCESS_TEXT}')"
# (The header button turning into "Applied" is also accepted; see apply_page.)
