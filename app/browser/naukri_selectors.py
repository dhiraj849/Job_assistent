"""Every CSS selector the apply flow and the detail-page reader use, in one place.

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
    # VERIFIED 2026-10-15 (tests/fixtures/naukri/already_applied.html; a <span>).
    # Naukri shows it after "Apply on company site" was clicked, even if
    # nothing was submitted on the company site (job 455).
    "already-applied": "already_applied",
}

# The "Apply on company site" button. A <button> with no href: the company
# URL is only known after clicking it (new tab or redirect).
# VERIFIED 2026-09-24 (tests/fixtures/naukri/company_site.html).
COMPANY_SITE_BUTTON = "#company-site-button"

# All header buttons that can hold the apply action. The text fallbacks catch
# a renamed id; classify_apply_button still decides by exact text.
APPLY_BUTTONS = ", ".join(
    [f"#{button_id}" for button_id in APPLY_BUTTON_IDS]
    + ["button:has-text('Apply')", "button:has-text('Applied')"]
)

# --- After clicking Apply ----------------------------------------------------------

# Naukri's "chatbot" drawer that asks screening questions one at a time.
# Seen live 2026-10-15 after one Apply click on job 1076
# (tests/fixtures/naukri/chatbot.html): a greeting, then one .botMsg per
# question; the last one is the open question. Some jobs show no greeting
# (job 7, tests/fixtures/naukri/chatbot_radio.html).
# VERIFIED 2026-10-15 (tests/fixtures/naukri/chatbot.html).
CHATBOT = ".chatbot_DrawerContentWrapper"
# VERIFIED 2026-10-15 (tests/fixtures/naukri/chatbot.html; greeting + question).
CHATBOT_BOT_MESSAGE = f"{CHATBOT} .botMsg"
# VERIFIED 2026-10-15 (tests/fixtures/naukri/chatbot.html): the footer's
# div.textArea; present but hidden (d-none) during a checkbox question.
# Typing into it is not verified live yet.
CHATBOT_TEXT_INPUT = f"{CHATBOT} [contenteditable='true']"
# VERIFIED 2026-10-15 (tests/fixtures/naukri/chatbot_radio.html, job 7):
# div.ssrc__radio-btn-container > input.ssrc__radio + label.ssrc__label (the
# option text, for= the input id); clicking the label checks the radio.
CHATBOT_RADIO_LABEL = f"{CHATBOT} .ssrc__radio-btn-container label"
# VERIFIED 2026-10-15 (tests/fixtures/naukri/chatbot.html): input.mcc__checkbox,
# each followed by its label.mcc__label (the option text, for= the input id).
CHATBOT_CHECKBOX = f"{CHATBOT} input[type='checkbox']"
CHATBOT_CHECKBOX_LABEL = f"{CHATBOT} label.mcc__label"
# VERIFIED 2026-10-15 (tests/fixtures/naukri/chatbot.html): div.sendMsg "Save"
# inside div.send, which has the class "disabled" until an answer is chosen.
CHATBOT_SEND = f"{CHATBOT} .sendMsg"

# Confirmation that the application went through: Naukri redirects to an
# "apply confirmation page" headed "Applied to <job title>".
# VERIFIED 2026-10-07 (tests/fixtures/naukri/apply_success.html).
APPLY_SUCCESS_CONTAINER = ".acp-header-container .job-title-text"
APPLY_SUCCESS_TEXT = "Applied to"
APPLY_SUCCESS = f"{APPLY_SUCCESS_CONTAINER}:has-text('{APPLY_SUCCESS_TEXT}')"
# (The header button turning into "Applied" is also accepted; see apply_page.)

# --- Job detail page (read only, no clicks) -----------------------------------------

# Primary source: the schema.org JobPosting JSON-LD block Naukri embeds for
# search engines. A public standard, so it changes far less than CSS classes.
# VERIFIED 2026-10-07 (tests/fixtures/naukri/job_detail_*.html, 3 companies).
JOB_POSTING_JSON_LD = "script[type='application/ld+json']"
JOB_POSTING_TYPE = "JobPosting"

# Fallback: the rendered JD block. Class names are CSS-module hashes
# ("styles_JDC__dang-inner-html__h0K4t"); the hash changes on Naukri deploys,
# so we match the part before it. The trailing "__" keeps it from matching
# longer names that share the prefix.
# VERIFIED 2026-10-07 (same fixtures).
JOB_DESCRIPTION_CLASS_PREFIX = "styles_JDC__dang-inner-html__"

# Either one present means the page has rendered far enough to read.
JOB_DETAIL_READY = f"{JOB_POSTING_JSON_LD}, [class*='{JOB_DESCRIPTION_CLASS_PREFIX}']"
