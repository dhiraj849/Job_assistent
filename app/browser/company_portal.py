"""Read a company career page (URL + HTML string): portal type, form fields, hard stops.

Pure functions, no browser: the inspector / applier fetches the HTML, this
file decides what it means, and tests run it on saved pages
(tests/fixtures/company_sites/). Markers and words live in
company_site_selectors.py.

Nothing here decides an answer. Anything unclear makes the page "unknown"
or adds a hard stop, so the caller stops (NEEDS_MANUAL) instead of filling.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

from app.browser.company_site_selectors import (
    CAPTCHA_CLASSES,
    CAPTCHA_RESPONSE_FIELDS,
    COMBOBOX_AUTOCOMPLETE,
    COMBOBOX_ROLE,
    HIDDEN_FIELD_ATTR,
    CAPTCHA_IFRAME_HINTS,
    CAPTCHA_INVISIBLE_SIZE,
    LOGIN_PHRASES,
    NEXT_BUTTON_TEXTS,
    OTP_FIELD_WORDS,
    PORTAL_DOMAINS,
    PORTAL_HTML_MARKERS,
    SENSITIVE_FIELD_WORDS,
    SUBMIT_BUTTON_TEXTS,
    VERIFICATION_PHRASES,
)


class PortalType(StrEnum):
    WORKDAY = "workday"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    SMARTRECRUITERS = "smartrecruiters"
    ICIMS = "icims"
    DARWINBOX = "darwinbox"
    KEKA = "keka"
    ZOHO_RECRUIT = "zoho_recruit"
    # A plain <form> with an email field and a file (resume) input.
    GENERIC_FORM = "generic_form"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FormField:
    # input type ("text", "email", "file", "radio", ...), or "textarea" / "select".
    kind: str
    # Best human-readable name: <label>, aria-label, placeholder, legend, then name.
    label: str
    name: str = ""
    id: str = ""
    autocomplete: str = ""
    required: bool = False
    # Choices of a <select> or a radio group; empty otherwise.
    options: tuple[str, ...] = ()
    # Index of the enclosing <form> on the page; None if outside any form
    # (React portals often have no <form> at all).
    form: int | None = None
    # False when the browser marked it hidden (HIDDEN_FIELD_ATTR): a honeypot
    # or a styled-away file input. Pages saved without the marker count as visible.
    visible: bool = True


@dataclass(frozen=True)
class PageReport:
    url: str
    portal: PortalType
    fields: list[FormField] = field(default_factory=list)
    # Human-readable reasons to stop; empty means "nothing scary seen".
    hard_stops: list[str] = field(default_factory=list)


# Hard stop for a form that exists but is not shown; find_job_opener may open it.
HIDDEN_FORM_STOP = "application form is hidden (opens from a button or modal)"
CAPTCHA_STOP = "CAPTCHA on the page"
OTP_STOP_PREFIX = "OTP / email verification"

# Input types that are not something a person fills in.
_SKIP_INPUT_TYPES = {"hidden", "submit", "button", "image", "reset"}
# Text inside these is not visible page text.
_INVISIBLE_TAGS = {"script", "style", "noscript", "template"}


def _norm(text: str) -> str:
    return " ".join(text.split())


class _PageParser(HTMLParser):
    """One pass over the HTML: raw fields, labels, buttons, visible text, CAPTCHA."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raw_fields: list[dict] = []
        self.label_for: dict[str, str] = {}
        self.buttons: list[str] = []
        self.text_parts: list[str] = []
        self.visible_captcha = False

        self._hidden_depth = 0
        self._form_count = 0
        self._form: int | None = None
        self._label: dict | None = None
        self._legends: list[str] = []
        self._in_legend = False
        self._select: dict | None = None
        self._option: list[str] | None = None
        self._button: list[str] | None = None

    # --- tags ---------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        if tag in _INVISIBLE_TAGS:
            self._hidden_depth += 1
            return
        self._check_captcha(tag, attrs)

        if tag == "form":
            self._form = self._form_count
            self._form_count += 1
        elif tag == "label":
            self._label = {"for": attrs.get("for", ""), "text": []}
        elif tag == "fieldset":
            self._legends.append("")
        elif tag == "legend":
            self._in_legend = True
        elif tag == "button":
            self._button = []
        elif tag == "input":
            kind = attrs.get("type", "text").lower() or "text"
            if kind in ("submit", "button"):
                self.buttons.append(_norm(attrs.get("value", "")))
            if kind not in _SKIP_INPUT_TYPES:
                is_combobox = (
                    attrs.get("role", "").lower() == COMBOBOX_ROLE
                    or attrs.get("aria-autocomplete", "").lower() == COMBOBOX_AUTOCOMPLETE
                )
                self._add_field("combobox" if is_combobox else kind, attrs)
        elif tag == "textarea":
            self._add_field("textarea", attrs)
        elif tag == "select":
            self._select = self._add_field("select", attrs)
        elif tag == "option" and self._select is not None:
            self._option = []

    def handle_endtag(self, tag):
        if tag in _INVISIBLE_TAGS:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if tag == "form":
            self._form = None
        elif tag == "label" and self._label is not None:
            text = _norm("".join(self._label["text"]))
            self._label["final"] = text
            if self._label["for"]:
                self.label_for[self._label["for"]] = text
            self._label = None
        elif tag == "fieldset" and self._legends:
            self._legends.pop()
        elif tag == "legend":
            self._in_legend = False
        elif tag == "button" and self._button is not None:
            self.buttons.append(_norm("".join(self._button)))
            self._button = None
        elif tag == "option" and self._option is not None and self._select is not None:
            text = _norm("".join(self._option))
            if text:
                self._select["options"].append(text)
            self._option = None
        elif tag == "select":
            self._select = None

    def handle_data(self, data):
        if self._hidden_depth:
            return
        self.text_parts.append(data)
        if self._label is not None:
            self._label["text"].append(data)
        if self._in_legend and self._legends:
            self._legends[-1] += data
        if self._option is not None:
            self._option.append(data)
        if self._button is not None:
            self._button.append(data)

    # --- helpers ------------------------------------------------------------

    def _add_field(self, kind: str, attrs: dict) -> dict:
        raw = {
            "visible": HIDDEN_FIELD_ATTR not in attrs,
            "kind": kind,
            "name": attrs.get("name", ""),
            "id": attrs.get("id", ""),
            "aria_label": attrs.get("aria-label", ""),
            "placeholder": attrs.get("placeholder", ""),
            "autocomplete": attrs.get("autocomplete", ""),
            "required": "required" in attrs or attrs.get("aria-required", "").lower() == "true",
            "value": attrs.get("value", ""),
            "legend": _norm(self._legends[-1]) if self._legends else "",
            # The wrapping <label>; its text is complete only after </label>.
            "label": self._label,
            "options": [],
            "form": self._form,
        }
        if raw["name"] not in CAPTCHA_RESPONSE_FIELDS:
            self.raw_fields.append(raw)
        return raw

    def _check_captcha(self, tag: str, attrs: dict) -> None:
        classes = attrs.get("class", "").split()
        if any(name in classes for name in CAPTCHA_CLASSES):
            if attrs.get("data-size", "").lower() != CAPTCHA_INVISIBLE_SIZE:
                self.visible_captcha = True
        if tag == "iframe":
            src = attrs.get("src", "")
            if any(hint in src for hint in CAPTCHA_IFRAME_HINTS) and "size=invisible" not in src:
                self.visible_captcha = True


# Marks of a required field in a label: "*" and Lever's "✱" (U+2731).
_REQUIRED_MARKS = ("*", "\u2731")


def _clean_label(text: str) -> tuple[str, bool]:
    """Strip the marks of a required field; return (label, starred)."""
    starred = any(mark in text for mark in _REQUIRED_MARKS)
    for mark in _REQUIRED_MARKS:
        text = text.replace(mark, "")
    return _norm(text), starred


def _own_label(raw: dict, label_for: dict[str, str]) -> str:
    wrapping = raw["label"]["final"] if raw["label"] and "final" in raw["label"] else ""
    return wrapping or label_for.get(raw["id"], "") or raw["aria_label"] or raw["placeholder"]


def _resolve_fields(parser: _PageParser) -> list[FormField]:
    # FormFields, plus one dict per radio group (resolved after all its inputs are seen).
    ordered: list[FormField | dict] = []
    radio_groups: dict[tuple, dict] = {}

    for raw in parser.raw_fields:
        own, starred = _clean_label(_own_label(raw, parser.label_for))
        required = raw["required"] or starred

        if raw["kind"] == "radio":
            # One question, many inputs: group by name inside the same form.
            key = (raw["form"], raw["name"] or raw["id"])
            group = radio_groups.get(key)
            if group is None:
                group = {"raw": raw, "options": [], "required": False}
                radio_groups[key] = group
                ordered.append(group)  # keeps page order
            group["options"].append(own or raw["value"])
            group["required"] = group["required"] or required
            group["visible"] = group.get("visible", False) or raw["visible"]
            continue

        legend, legend_star = _clean_label(raw["legend"])
        ordered.append(
            FormField(
                kind=raw["kind"],
                label=own or legend or raw["name"],
                name=raw["name"],
                id=raw["id"],
                autocomplete=raw["autocomplete"],
                required=required or (not own and legend_star),
                options=tuple(raw["options"]),
                form=raw["form"],
                visible=raw["visible"],
            )
        )

    resolved = []
    for item in ordered:
        if isinstance(item, FormField):
            resolved.append(item)
            continue
        raw = item["raw"]
        legend, legend_star = _clean_label(raw["legend"])
        resolved.append(
            FormField(
                kind="radio",
                label=legend or raw["name"],
                name=raw["name"],
                id=raw["id"],
                autocomplete=raw["autocomplete"],
                required=item["required"] or legend_star,
                options=tuple(item["options"]),
                form=raw["form"],
                visible=item["visible"],
            )
        )
    return resolved


def _parse(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return parser


def parse_form_fields(html: str) -> list[FormField]:
    """Every fillable field on the page, in page order (radio groups merged)."""
    return _resolve_fields(_parse(html))


# --- Portal type ------------------------------------------------------------------


def _portal_from_url(url: str) -> PortalType | None:
    host = (urlparse(url).hostname or "").lower()
    for domain, portal in PORTAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return PortalType(portal)
    return None


def _is_email_field(f: FormField) -> bool:
    return f.kind == "email" or "email" in f"{f.autocomplete} {f.name} {f.label}".lower()


def _application_forms(fields: list[FormField]) -> list[list[FormField]]:
    """Fields of each <form> with an email field and a file input: an application,
    not a search or job-alert box."""
    forms = sorted({f.form for f in fields if f.form is not None})
    found = []
    for form in forms:
        in_form = [f for f in fields if f.form == form]
        if any(_is_email_field(f) for f in in_form) and any(f.kind == "file" for f in in_form):
            found.append(in_form)
    return found


def application_form(fields: list[FormField]) -> list[FormField]:
    """Fields of the form to fill: the first application form whose email field is visible.

    Empty if there is none (or it is still hidden in a closed modal).
    """
    for form in _application_forms(fields):
        if any(f.visible and _is_email_field(f) for f in form):
            return form
    return []


def detect_portal(url: str, html: str, fields: list[FormField] | None = None) -> PortalType:
    """URL first (most reliable), then embed markers in the HTML, then a generic form."""
    by_url = _portal_from_url(url)
    if by_url:
        return by_url
    lowered = html.lower()
    for marker, portal in PORTAL_HTML_MARKERS.items():
        if marker.lower() in lowered:
            return PortalType(portal)
    if _application_forms(fields if fields is not None else parse_form_fields(html)):
        return PortalType.GENERIC_FORM
    return PortalType.UNKNOWN


# --- Hard stops ---------------------------------------------------------------------


def _field_words(f: FormField) -> str:
    return _norm(f"{f.label} {f.name} {f.id}".replace("_", " ").replace("-", " ")).lower()


def _mentions(text: str, words: tuple[str, ...]) -> str | None:
    """The first word found on a word boundary ("bank" yes, "bankruptcy" no)."""
    for word in words:
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text):
            return word
    return None


def _hard_stops(
    portal: PortalType, parser: _PageParser, fields: list[FormField]
) -> list[str]:
    stops: list[str] = []
    text = _norm(" ".join(parser.text_parts)).lower()

    if portal == PortalType.WORKDAY:
        stops.append("login required: Workday asks for an account before applying")
    if any(f.kind == "password" for f in fields):
        stops.append("login or account creation required (password field)")
    if phrase := _mentions(text, LOGIN_PHRASES):
        stops.append(f"login or account creation required (page says {phrase!r})")

    if phrase := _mentions(text, VERIFICATION_PHRASES):
        stops.append(f"{OTP_STOP_PREFIX} (page says {phrase!r})")
    for f in fields:
        if _mentions(_field_words(f), OTP_FIELD_WORDS):
            stops.append(f"{OTP_STOP_PREFIX} (field {f.label!r})")
        elif word := _mentions(_field_words(f), SENSITIVE_FIELD_WORDS):
            stops.append(f"asks for sensitive data ({word}): field {f.label!r}")

    # The form exists but the person cannot see it: it opens from a button,
    # e.g. a per-job "Apply" link that opens a modal (kmgus.com, 2026-10-15).
    # The file input is not checked: sites often hide it behind a styled button.
    forms = _application_forms(fields)
    if forms and not any(f.visible and _is_email_field(f) for form in forms for f in form):
        stops.append(HIDDEN_FORM_STOP)

    if parser.visible_captcha:
        stops.append(CAPTCHA_STOP)

    buttons = {text.lower() for text in parser.buttons if text}
    if buttons & set(NEXT_BUTTON_TEXTS) and not buttons & set(SUBMIT_BUTTON_TEXTS):
        stops.append("multi-step form we don't recognise (Next/Continue, no Submit)")
    return stops


def split_stops(stops: list[str]) -> tuple[list[str], list[str]]:
    """(human_steps, blocking): a CAPTCHA or OTP is a step I do during the
    fill session; every other stop means the site is not for the filler."""
    steps, blocking = [], []
    for stop in stops:
        if stop == CAPTCHA_STOP:
            steps.append("captcha")
        elif stop.startswith(OTP_STOP_PREFIX):
            steps.append("otp")
        else:
            blocking.append(stop)
    return sorted(set(steps)), blocking


def inspect_page(url: str, html: str) -> PageReport:
    """Everything the inspector prints and the filler checks, for one page or frame."""
    parser = _parse(html)
    fields = _resolve_fields(parser)
    portal = detect_portal(url, html, fields)
    return PageReport(url=url, portal=portal, fields=fields, hard_stops=_hard_stops(portal, parser, fields))


# --- Opening a hidden form ----------------------------------------------------------

# A link we may click only if it cannot leave the page or send anything:
# no href, an in-page anchor, or a script call.
_IN_PAGE_HREF = re.compile(r"^\s*(#|javascript:|$)", re.IGNORECASE)
# Quoted arguments in an onclick, e.g. Enquiry('Python Developer').
_QUOTED = re.compile(r"""(['"])(.*?)\1""")


class _OpenerParser(HTMLParser):
    """(tag, attrs) of every <a> / <button> with an onclick."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.openers: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        if tag in ("a", "button") and attrs.get("onclick"):
            self.openers.append((tag, attrs))


def find_job_opener(html: str, job_title: str) -> str | None:
    """CSS selector of the one in-page link that opens this job's form, or None.

    Careers lists like kmgus.com (2026-10-15) share one hidden form between
    all jobs; each job's "Apply" link opens it with the title as the onclick
    argument. Only an exact title match counts, only in-page links (nothing
    is loaded or sent by the click), and exactly one must match: anything
    else returns None and the hidden-form stop stays.
    """
    wanted = _norm(job_title).lower()
    if not wanted:
        return None
    parser = _OpenerParser()
    parser.feed(html)
    parser.close()

    matches = []
    for tag, attrs in parser.openers:
        if tag == "a" and not _IN_PAGE_HREF.match(attrs.get("href", "")):
            continue
        arguments = [_norm(value).lower() for _, value in _QUOTED.findall(attrs["onclick"])]
        if wanted in arguments:
            matches.append((tag, attrs["onclick"]))
    if len(set(matches)) != 1:
        return None
    tag, onclick = matches[0]
    escaped = onclick.replace("\\", "\\\\").replace('"', '\\"')
    return f'{tag}[onclick="{escaped}"]'


# --- Opening the job's own page ----------------------------------------------------

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _JobLinkParser(HTMLParser):
    """For each heading that is exactly the job title: the first "apply" link
    after it, before the next heading of the same or a higher level (the next job)."""

    def __init__(self, wanted: str):
        super().__init__(convert_charrefs=True)
        self.wanted = wanted
        # One entry per title heading: its apply link's href, or None.
        self.rows: list[str | None] = []
        self._heading: tuple[int, list[str]] | None = None
        self._row_level: int | None = None  # set while inside this job's row
        self._link: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        if tag in _HEADINGS:
            self._heading = (int(tag[1]), [])
        elif tag == "a" and self._row_level is not None and self.rows[-1] is None:
            self._link = (attrs.get("href", ""), [])

    def handle_endtag(self, tag):
        if tag in _HEADINGS and self._heading is not None:
            level, parts = self._heading
            self._heading = None
            if _norm("".join(parts)).lower() == self.wanted:
                self.rows.append(None)
                self._row_level = level
            elif self._row_level is not None and level <= self._row_level:
                self._row_level = None  # the next job starts
        elif tag == "a" and self._link is not None:
            href, parts = self._link
            self._link = None
            if "apply" in _norm("".join(parts)).lower():
                self.rows[-1] = href

    def handle_data(self, data):
        if self._heading is not None:
            self._heading[1].append(data)
        if self._link is not None:
            self._link[1].append(data)


def find_job_page_link(html: str, page_url: str, job_title: str) -> str | None:
    """Absolute URL of this job's "Apply" link to another page of the same site, or None.

    For a careers list with no form at all, where each job's "Apply Now" is a
    plain link (zaax.com 2026-10-15: every role links to one shared
    /submit-resume/ form). Opening it is an ordinary page load: nothing is
    sent. Only a heading that is exactly the job title counts, it must appear
    once, and the link must be http(s) on the same host and not this page.
    """
    wanted = _norm(job_title).lower()
    if not wanted:
        return None
    parser = _JobLinkParser(wanted)
    parser.feed(html)
    parser.close()
    if len(parser.rows) != 1 or not parser.rows[0]:
        return None

    link = urljoin(page_url, parser.rows[0])
    target, here = urlparse(link), urlparse(page_url)
    if target.scheme not in ("http", "https") or target.hostname != here.hostname:
        return None
    if urldefrag(link).url == urldefrag(page_url).url:
        return None  # an anchor on this page ("#openings")
    return link
