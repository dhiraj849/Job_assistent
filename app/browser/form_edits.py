"""Answers I typed or changed in the browser that may become learned answers.

The page reports its form values (company_site_page.read_form_values /
watch_form); this file decides which of them are worth saving to
learned_answers.yaml. Pure functions, no browser. Nothing is saved here:
the caller asks me y/N for each edit first.
"""

from dataclasses import dataclass

from app.browser.company_form_mapper import FIXED_RULES, TEXT_KINDS, MappedField
from app.browser.company_portal import FormField
from app.browser.company_site_selectors import OTP_FIELD_WORDS, SENSITIVE_FIELD_WORDS
from app.services.learned_answers import LearnedAnswers

# Kinds a learned answer can fill later (map_field). Checkboxes are consents,
# dates and files are never auto-filled, so saving them would be useless.
LEARNABLE_KINDS = TEXT_KINDS | {"select", "radio"}
# Never stored, whatever I typed: secrets, one-time codes, ID / bank numbers.
_SECRET_WORDS = ("password", "captcha", "signature", *OTP_FIELD_WORDS, *SENSITIVE_FIELD_WORDS)


@dataclass(frozen=True)
class BrowserEdit:
    field: FormField
    # What the browser shows now (an option's text for a select / radio).
    value: str
    # What the script filled; None if it left the field empty.
    before: str | None
    # Set when the field came from answers.yaml: the fix belongs there, not in learned answers.
    fixed_rule: str | None = None


def _norm(text: str) -> str:
    return " ".join(text.split())


def _is_secret(field: FormField) -> bool:
    text = f"{field.label} {field.name} {field.id}".lower()
    return any(word in text for word in _SECRET_WORDS)


def _value_of(field: FormField, values: list[dict]) -> str:
    """The field's current value from the page's report, "" if unset or not found."""
    if field.kind == "radio":
        checked = [v for v in values if v.get("type") == "radio" and v.get("name") == field.name]
        return _norm(checked[0].get("value", "")) if len(checked) == 1 else ""
    key, wanted = ("id", field.id) if field.id else ("name", field.name)
    found = [v for v in values if v.get(key) == wanted and v.get("type") != "radio"]
    return _norm(found[0].get("value", "")) if len(found) == 1 else ""


def browser_edits(
    mapped: list[MappedField],
    values: list[dict],
    learned: LearnedAnswers,
    baseline: list[dict] | None = None,
) -> list[BrowserEdit]:
    """Fields I changed in the browser after the script filled the form.

    values: one dict per element (name, id, type, value), as
    company_site_page reports them. baseline: the same, read right after
    the fill, so a value the page pre-selects (zaax.com: Country = India)
    is not taken as mine; without it, what the script filled is the baseline.
    Skips hidden fields (honeypots), secrets, kinds a learned answer cannot
    fill, values that fit no option, and answers already saved for that label.
    """
    edits = []
    for item in mapped:
        field = item.field
        if not field.visible or field.kind not in LEARNABLE_KINDS or _is_secret(field):
            continue
        value = _value_of(field, values)
        if not value:
            continue
        if field.options and value not in field.options:
            continue  # a placeholder ("Select") or text we cannot match later
        before = item.answer.value if item.answer else None
        start = _value_of(field, baseline) if baseline is not None else _norm(before or "")
        if value == start:
            continue
        rule = item.answer.rule if item.answer else None
        if rule in FIXED_RULES:
            edits.append(BrowserEdit(field, value, before, fixed_rule=rule))
            continue
        if learned.get(field.label) == value:
            continue
        edits.append(BrowserEdit(field, value, before))
    return edits
