"""Map a company-site form field to a value from answers.yaml.

Deterministic rules, no LLM, like apply_questions.py: the same field always
gets the same value, and every value can be traced to one rule. Rules:

- hidden fields are never filled (spam honeypots look like real fields);
- checkboxes are never ticked: they are consents, a human decides;
- exactly one contact rule must match, otherwise no answer (ambiguous);
- fields no contact rule knows go to apply_questions.map_question (notice
  period, CTC, experience, location, relocation), then to the answers I
  approved before (learned_answers.yaml);
- what is still unknown may get an AI suggestion (app/llm/form_answerer.py),
  but never for the topics in AI_FORBIDDEN_WORDS, and only after my approval;
- no answer means the field stays empty and the reason says why. The caller
  decides what that means (preview: left for you; filler: NEEDS_MANUAL if
  the field is required).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.browser.apply_questions import Question, map_question
from app.browser.company_portal import FormField
from app.models.application_answers import ApplicationAnswers, ContactAnswers
from app.services.learned_answers import LearnedAnswers

# The reason for a field no rule knows: the only kind the AI may suggest for.
NO_RULE = "no rule knows this field"

# Topics a human always answers: identity and legal facts, protected
# characteristics, consents, and money/notice (fixed rules only, so a
# number never comes from a model).
AI_FORBIDDEN_WORDS = (
    "gender", "sex", "caste", "religion", "disability", "disabled", "veteran",
    "ethnicity", "ethnic", "race", "marital", "criminal", "convicted", "conviction",
    "arrest", "declaration", "declare", "date of birth", "dob", "birth", "age",
    "password", "signature", "consent", "agree", "terms", "salary", "ctc",
    "compensation", "package", "notice", "aadhaar", "aadhar", "pan", "passport",
    "bank", "visa", "sponsorship", "authorized", "authorised", "authorization",
    "authorisation", "government", "politically", "family member", "relative",
)

# Field kinds a value is typed into.
TEXT_KINDS = {"text", "email", "tel", "url", "number", "textarea"}
# Field kinds we fill at all (others, e.g. date or password, need a human).
FILLABLE_KINDS = TEXT_KINDS | {"select", "radio", "file"}

# "name" in a label means the person's full name, unless one of these says
# it is some other name ("Company name", "Father's name", "File name").
_OTHER_NAMES = (
    "first", "last", "given", "family", "middle", "sur", "company", "organization",
    "organisation", "org", "employer", "user", "father", "mother", "spouse",
    "reference", "referrer", "referred", "referral", "their", "employee", "manager",
    "recruiter", "emergency", "nominee", "college", "school", "university", "file", "job",
    "project",
)


@dataclass(frozen=True)
class FieldAnswer:
    # Text to type, option to pick, or the file path to upload.
    value: str
    # Which rule decided it, so a human can check the reasoning.
    rule: str


@dataclass(frozen=True)
class MappedField:
    field: FormField
    answer: FieldAnswer | None
    # Why there is no answer (empty when there is one).
    reason: str = ""


def _words(field: FormField) -> str:
    """Label, name, id and autocomplete as one lowercase string of words."""
    text = f"{field.label} {field.name} {field.id} {field.autocomplete}"
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # "UploadResume" -> "Upload Resume"
    text = re.sub(r"[_\-\[\]./]", " ", text)
    return " ".join(text.lower().split())


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _is_email(f: FormField, w: str) -> bool:
    return f.kind == "email" or f.autocomplete == "email" or _has(w, "email", "e mail")


# A tel field that asks for some other number than my mobile (zaax.com has
# a separate "Landline Number" tel field, 2026-10-15).
_OTHER_PHONES = ("landline", "fax", "alternate", "alternative", "emergency", "office", "reference")


def _is_phone(f: FormField, w: str) -> bool:
    if _has(w, *_OTHER_PHONES):
        return False
    return (
        f.kind == "tel"
        or f.autocomplete.startswith("tel")
        or _has(w, "phone", "mobile", "contact number", "whatsapp")
    )


def _is_first_name(f: FormField, w: str) -> bool:
    return f.autocomplete == "given-name" or _has(w, "first name", "given name", "fname")


def _is_last_name(f: FormField, w: str) -> bool:
    return f.autocomplete == "family-name" or _has(w, "last name", "surname", "family name", "lname")


def _is_full_name(f: FormField, w: str) -> bool:
    if f.autocomplete == "name":
        return True
    # A question that mentions a name ("Were you referred? ... provide their
    # name", Greenhouse 2026-10-15) asks about someone else, not me.
    if "?" in f.label:
        return False
    return _has(w, "name", "full name") and not _has(w, *_OTHER_NAMES)


def _is_linkedin(f: FormField, w: str) -> bool:
    return _has(w, "linkedin", "linked in")


@dataclass(frozen=True)
class _ContactRule:
    name: str
    kinds: frozenset[str]
    matches: Callable[[FormField, str], bool]
    value: Callable[[ContactAnswers], str]


_CONTACT_RULES = [
    _ContactRule("email", frozenset(TEXT_KINDS), _is_email, lambda c: c.email),
    _ContactRule("phone", frozenset(TEXT_KINDS), _is_phone, lambda c: c.phone),
    _ContactRule("first_name", frozenset(TEXT_KINDS), _is_first_name, lambda c: c.first_name),
    _ContactRule("last_name", frozenset(TEXT_KINDS), _is_last_name, lambda c: c.last_name),
    _ContactRule("full_name", frozenset(TEXT_KINDS), _is_full_name, lambda c: c.full_name),
    _ContactRule("linkedin_url", frozenset(TEXT_KINDS), _is_linkedin, lambda c: c.linkedin_url),
    _ContactRule(
        "resume",
        frozenset({"file"}),
        lambda f, w: _has(w, "resume", "cv", "curriculum vitae"),
        lambda c: str(c.resume_path),
    ),
]


SCREENING_RULE = "screening question"
# Rules whose value comes from answers.yaml: a change I make in the browser
# belongs in answers.yaml, not in learned_answers.yaml (these rules win anyway).
FIXED_RULES = frozenset({rule.name for rule in _CONTACT_RULES} | {SCREENING_RULE})


def _no(field: FormField, reason: str) -> MappedField:
    return MappedField(field=field, answer=None, reason=reason)


def _pick_option(value: str, options: tuple[str, ...]) -> str | None:
    fitting = [o for o in options if " ".join(o.lower().split()) == " ".join(value.lower().split())]
    return fitting[0] if len(fitting) == 1 else None


def ai_forbidden_reason(field: FormField) -> str | None:
    """Why the AI must not suggest for this field, or None if it may."""
    if word := next((w for w in AI_FORBIDDEN_WORDS if _has(_words(field), w)), None):
        return f"AI never answers this ({word}): you decide"
    return None


def map_field(
    field: FormField, answers: ApplicationAnswers, learned: LearnedAnswers | None = None
) -> MappedField:
    """The value for one field, or no answer with the reason."""
    if not field.visible:
        return _no(field, "hidden field: never filled (may be a spam trap)")
    if field.kind == "checkbox":
        return _no(field, "checkbox (consent): you decide")
    if field.kind == "combobox":
        return _no(field, "dropdown with search: you pick it in the browser")
    if field.kind not in FILLABLE_KINDS:
        return _no(field, f"{field.kind} field: not filled automatically")

    words = _words(field)
    matched = [rule for rule in _CONTACT_RULES if field.kind in rule.kinds and rule.matches(field, words)]
    if len(matched) > 1:
        names = ", ".join(rule.name for rule in matched)
        return _no(field, f"ambiguous: matches {names}")
    if matched:
        rule = matched[0]
        if answers.contact is None:
            return _no(field, f"{rule.name}: no contact block in answers.yaml")
        value = rule.value(answers.contact)
        if not value:
            return _no(field, f"{rule.name}: empty in answers.yaml")
        if rule.name == "resume" and not answers.contact.resume_path.is_file():
            return _no(field, f"resume: file not found: {value}")
        return MappedField(field=field, answer=FieldAnswer(value=value, rule=rule.name))

    if field.kind == "file":
        return _no(field, "file upload that is not a resume")

    # Screening-style fields ("Notice period", "Expected CTC"): same rules as Naukri.
    question = Question(text=field.label, options=list(field.options))
    value = map_question(question, answers)
    if value is not None:
        return MappedField(field=field, answer=FieldAnswer(value=value, rule=SCREENING_RULE))

    # An answer I approved earlier for the same label.
    if learned is not None and (saved := learned.get(field.label)) is not None:
        if field.options:
            option = _pick_option(saved, field.options)
            if option is None:
                return _no(field, f"learned answer {saved!r} is not one of the options")
            saved = option
        return MappedField(field=field, answer=FieldAnswer(value=saved, rule="learned"))
    return _no(field, NO_RULE)


def map_form(
    fields: list[FormField], answers: ApplicationAnswers, learned: LearnedAnswers | None = None
) -> list[MappedField]:
    return [map_field(field, answers, learned) for field in fields]
