"""How we recognise a company career site: URL patterns, markers and words.

Company portals are third-party sites that change without notice; when
detection breaks, this is the only file to fix. Each entry says where it
was checked:

- VERIFIED <date>: seen in a saved live page (tests/fixtures/company_sites/).
- NOT VERIFIED: from public ATS markup, no live sample yet. Detection is
  written so a wrong entry here makes the page "unknown" or adds a hard stop
  (NEEDS_MANUAL), never lets a form be filled by mistake.
  Verify with scripts/inspect_company_site.py.
"""

# --- Portal type from the URL ---------------------------------------------------

# Hostname suffix -> portal type value (see company_portal.PortalType).
# Matched on the domain boundary, so "lever.co" covers "jobs.eu.lever.co".
# NOT VERIFIED (all).
PORTAL_DOMAINS = {
    "myworkdayjobs.com": "workday",
    "myworkdaysite.com": "workday",
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "smartrecruiters.com": "smartrecruiters",
    "icims.com": "icims",
    # Common with Indian companies; detected only, never filled in v1.
    "darwinbox.in": "darwinbox",
    "darwinbox.com": "darwinbox",
    "keka.com": "keka",
    "zohorecruit.com": "zoho_recruit",
    "zohorecruit.in": "zoho_recruit",
}

# --- Portal type from the HTML (ATS embedded in the company's own page) ---------

# Substring of the page HTML -> portal type value. Only embed markers: a plain
# link to jobs.lever.co on a careers list does not mean the form is here.
# NOT VERIFIED (all).
PORTAL_HTML_MARKERS = {
    "boards.greenhouse.io/embed": "greenhouse",
    "job-boards.greenhouse.io/embed": "greenhouse",
    'id="grnhse_app"': "greenhouse",
    'data-automation-id="jobpostingpage"': "workday",
}

# --- Fields that are not for a person ---------------------------------------------

# Filled by the CAPTCHA script itself, never by us.
# VERIFIED 2026-10-15 (g-recaptcha-response, tests/fixtures/company_sites/generic_kmgus.html).
CAPTCHA_RESPONSE_FIELDS = ("g-recaptcha-response", "h-captcha-response", "cf-turnstile-response")

# Set by company_site_page.read_documents on every field the browser does not
# show (display:none, zero size, ...) before the HTML is saved. Hidden fields
# include spam honeypots (e.g. Contact Form 7's "_wpcf7_ak_hp_textarea", seen
# 2026-10-15): filling one gets the application dropped as spam.
HIDDEN_FIELD_ATTR = "data-jobagent-hidden"

# Searchable dropdowns (react-select, Greenhouse's new job boards): an input
# the person types into to pick an option. Not filled automatically.
# VERIFIED 2026-10-15 (greenhouse_tower_frame.html: class select__input,
# aria-autocomplete="list").
COMBOBOX_ROLE = "combobox"
COMBOBOX_AUTOCOMPLETE = "list"

# --- Hard stops -------------------------------------------------------------------

# Visible page text that means an account is needed before applying.
# NOT VERIFIED.
LOGIN_PHRASES = (
    "sign in to apply",
    "log in to apply",
    "login to apply",
    "create an account",
    "create account",
    "register to apply",
)

# Visible page text that means an OTP / email check is waiting.
# NOT VERIFIED.
VERIFICATION_PHRASES = ("enter the otp", "enter otp", "verify your email", "verification code")

# Words in a field's label/name that mean an OTP field.
OTP_FIELD_WORDS = ("otp", "one time password", "one-time password", "verification code")

# Words in a field's label/name we must never fill: IDs, bank, payment.
# Only fields are checked, not page text: a JD saying "PAN India" or
# "payments team" must not stop anything.
SENSITIVE_FIELD_WORDS = (
    "aadhaar",
    "aadhar",
    "pan number",
    "pan card",
    "pan no",
    "permanent account number",
    # Not plain "bank": a PEP declaration mentions "World Bank" (Greenhouse,
    # Tower Research, 2026-10-15) and is not a bank-details field.
    "bank account",
    "bank name",
    "bank details",
    "bank branch",
    "ifsc",
    "account number",
    "passport",
    "ssn",
    "social security",
    "card number",
    "cvv",
    "upi",
    "payment",
)

# CAPTCHA widgets. Only a visible one is a stop: Lever/Greenhouse load an
# invisible one that runs on submit, and we never submit. A widget div with
# data-size="invisible" (or an iframe URL with size=invisible) is ignored.
# hCaptcha's iframes are left out: its hidden challenge iframe exists even
# for the invisible widget, so only the h-captcha div decides.
# Invisible reCAPTCHA (anchor iframe with size=invisible) correctly ignored:
# VERIFIED 2026-10-15 (generic_kmgus.html). A visible one: NOT VERIFIED.
CAPTCHA_CLASSES = ("g-recaptcha", "h-captcha", "cf-turnstile")
CAPTCHA_INVISIBLE_SIZE = "invisible"
CAPTCHA_IFRAME_HINTS = ("recaptcha/api2/anchor", "challenges.cloudflare.com")

# Button texts. A "Next"/"Continue" with no submit button is a wizard we do
# not know how to walk (v1 fills one page only).
# NOT VERIFIED.
NEXT_BUTTON_TEXTS = ("next", "continue", "save and continue", "save & continue", "proceed")
# "send": VERIFIED 2026-10-15 (kmgus.com resume form, generic_kmgus_form_open.html).
SUBMIT_BUTTON_TEXTS = ("submit", "submit application", "apply", "apply now", "send application", "send")
