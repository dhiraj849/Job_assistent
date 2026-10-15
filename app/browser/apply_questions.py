"""Map a Naukri screening question to an answer from answers.yaml.

Deterministic keyword rules, no LLM: the same question always gets the same
answer, and every answer can be traced to one rule. Anything unclear returns
None and the apply stops for a human (NEEDS_MANUAL). Rules:

- exactly one rule must match the question, otherwise None (ambiguous);
- with options, exactly one option must fit the value, otherwise None;
- free-text answers say their unit ("30 days", "14 LPA") unless the question
  names one, so a recruiter can never misread the number.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.models.application_answers import ApplicationAnswers


@dataclass(frozen=True)
class Question:
    text: str
    # Visible choices (radio buttons); empty for a free-text question.
    options: list[str] = field(default_factory=list)
    # Checkbox questions can need several ticks; never answered automatically.
    multi_select: bool = False


# --- Parsing helpers -----------------------------------------------------------

_NUMBER = r"(\d+(?:\.\d+)?)"
_DAYS_PER_UNIT = {"day": 1, "week": 7, "month": 30}


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(word)}", text) for word in words)


def _fmt(value: float) -> str:
    """14.0 -> "14", 4.5 -> "4.5"."""
    return f"{value:g}"


def _numeric_range(option: str, unit_scale: Callable[[str], float | None]) -> tuple[float, float] | None:
    """Turn an option like "5-10 Lakhs", "15 Days or less", "3+ years" into (low, high).

    unit_scale converts the option's own unit (e.g. months -> days); it returns
    None when the option has no understandable unit.
    """
    text = _norm(option)
    scale = unit_scale(text)
    if scale is None:
        return None

    numbers = [float(n) for n in re.findall(_NUMBER, text)]
    if len(numbers) == 2 and re.search(rf"{_NUMBER}\D*?(?:-|–|to)\D*?{_NUMBER}", text):
        return numbers[0] * scale, numbers[1] * scale
    if len(numbers) == 1:
        value = numbers[0] * scale
        if _has(text, "less", "upto", "up to", "below", "within") or "<" in text:
            return 0.0, value
        if _has(text, "more", "above", "over", "plus") or "+" in text or ">" in text:
            # "More than 3 months" excludes 90 itself; nudge past it.
            strict = _has(text, "more", "over") or ">" in text
            return value + (1e-9 if strict else 0.0), float("inf")
        return value, value
    return None


def _pick_numeric(value: float, options: list[str], unit_scale) -> str | None:
    fitting = [
        option
        for option in options
        if (bounds := _numeric_range(option, unit_scale)) and bounds[0] <= value <= bounds[1]
    ]
    return fitting[0] if len(fitting) == 1 else None


def _pick_text(wanted: str, options: list[str]) -> str | None:
    fitting = [option for option in options if _norm(option) == _norm(wanted)]
    return fitting[0] if len(fitting) == 1 else None


def _pick_place(place: str, options: list[str]) -> str | None:
    """The one option naming my city, also inside a group ("Noida / Delhi / Gurgaon",
    Naukri chatbot 2026-10-15). Exact matches win; two fitting options mean None."""
    if exact := _pick_text(place, options):
        return exact
    wanted = _norm(place)
    fitting = [o for o in options if wanted in (_norm(part) for part in re.split(r"[/,|]", o))]
    return fitting[0] if len(fitting) == 1 else None


# --- Unit scales ---------------------------------------------------------------


def _days_scale(text: str) -> float | None:
    if _has(text, "immediate"):
        return 1.0  # "Immediate" has no number; handled in _notice_answer
    for unit, days in _DAYS_PER_UNIT.items():
        if _has(text, unit):
            return float(days)
    return None


def _lakh_scale(text: str) -> float | None:
    return 1.0 if _has(text, "lakh", "lac", "lpa") else None


def _years_scale(text: str) -> float | None:
    return 1.0 if _has(text, "year", "yr") else None


# --- Answers per topic ---------------------------------------------------------


def _notice_answer(question: Question, text: str, answers: ApplicationAnswers) -> str | None:
    days = answers.notice_period_days
    if question.options:
        if days == 0:
            immediate = [o for o in question.options if _has(_norm(o), "immediate")]
            if len(immediate) == 1:
                return immediate[0]
        return _pick_numeric(days, question.options, _days_scale)
    if _has(text, "in days"):
        return str(days)
    if _has(text, "in months"):
        return str(days // 30) if days % 30 == 0 else None
    return f"{days} days"


def _ctc_answer(lpa: float) -> Callable[[Question, str, ApplicationAnswers], str | None]:
    def answer(question: Question, text: str, _: ApplicationAnswers) -> str | None:
        if question.options:
            # The question may carry the unit ("CTC in lakhs") for bare-number options.
            question_scale = _lakh_scale(text)
            return _pick_numeric(
                lpa, question.options, lambda option: _lakh_scale(option) or question_scale
            )
        if _has(text, "lakh", "lac", "lpa"):
            return _fmt(lpa)
        if _has(text, "rupees", "inr", "rs"):
            return str(round(lpa * 100_000))
        return f"{_fmt(lpa)} LPA"

    return answer


def _years_answer(years: float, question: Question, text: str) -> str | None:
    if question.options:
        question_scale = _years_scale(text)
        return _pick_numeric(
            years, question.options, lambda option: _years_scale(option) or question_scale
        )
    return _fmt(years)


def _yes_no(value: bool, question: Question) -> str | None:
    wanted = "yes" if value else "no"
    return _pick_text(wanted, question.options) if question.options else wanted.capitalize()


# --- Rules ---------------------------------------------------------------------

_CTC_WORDS = ("ctc", "salary", "package", "compensation")


def _skills_in(text: str, answers: ApplicationAnswers) -> list[str]:
    return [
        skill
        for skill in answers.skill_years
        if re.search(rf"(?<![\w+#.]){re.escape(skill.lower())}(?![\w+#])", text)
    ]


def _is_skill_years(text: str, answers: ApplicationAnswers) -> bool:
    return _has(text, "year", "experience") and bool(_skills_in(text, answers))


def _skill_years_answer(question: Question, text: str, answers: ApplicationAnswers) -> str | None:
    skills = _skills_in(text, answers)
    if len(skills) != 1:
        return None  # "Python and Django experience?" has no single number
    return _years_answer(answers.skill_years[skills[0]], question, text)


# A yes/no question ("Are you serving notice?", "Can you join in 15 days?")
# must never get a number or a city as its answer.
_YES_NO_START = re.compile(r"^(are|is|do|does|did|have|has|can|could|will|would|shall)\b")


def _is_yes_no(text: str) -> bool:
    return bool(_YES_NO_START.match(text))


def _is_total_experience(text: str, answers: ApplicationAnswers) -> bool:
    if not _has(text, "experience") or _skills_in(text, answers) or _has(text, "relevant"):
        return False
    if _has(text, "total", "overall"):
        return True
    # "How many years of experience do you have?" is total experience, but
    # "... experience do you have in Kafka?" is about a skill we don't know.
    tail = text.split("experience", 1)[1]
    return _has(text, "year") and not _has(tail, "in", "with", "on", "of", "using", "as")


@dataclass(frozen=True)
class _Rule:
    name: str
    matches: Callable[[str, ApplicationAnswers], bool]
    answer: Callable[[Question, str, ApplicationAnswers], str | None]
    # False for rules whose answer is a value: they skip yes/no questions.
    yes_no: bool = False


def _rules(answers: ApplicationAnswers) -> list[_Rule]:
    return [
        _Rule(
            "notice_period",
            lambda t, a: _has(t, "notice period") or (_has(t, "join") and _has(t, "soon", "early", "when")),
            _notice_answer,
        ),
        _Rule(
            "expected_ctc",
            lambda t, a: _has(t, "expected") and _has(t, *_CTC_WORDS),
            _ctc_answer(answers.expected_ctc_lpa),
        ),
        _Rule(
            "current_ctc",
            lambda t, a: _has(t, "current", "present") and _has(t, *_CTC_WORDS),
            _ctc_answer(answers.current_ctc_lpa),
        ),
        _Rule(
            "relocate",
            lambda t, a: _has(t, "relocat"),
            lambda q, t, a: _yes_no(a.willing_to_relocate, q),
            yes_no=True,
        ),
        _Rule(
            "current_location",
            lambda t, a: _has(t, "current location", "currently located", "currently based", "currently residing"),
            lambda q, t, a: _pick_place(a.current_location, q.options) if q.options else a.current_location,
        ),
        _Rule("skill_years", _is_skill_years, _skill_years_answer),
        _Rule(
            "total_experience",
            _is_total_experience,
            lambda q, t, a: _years_answer(a.total_experience_years, q, t),
        ),
    ]


def map_question(question: Question, answers: ApplicationAnswers) -> str | None:
    """The answer to type or the option to pick, or None if a human must answer."""
    if question.multi_select:
        return None
    text = _norm(question.text)
    matched = [rule for rule in _rules(answers) if rule.matches(text, answers)]
    if len(matched) != 1:
        return None
    rule = matched[0]
    # Value rules skip yes/no questions; the yes/no rule needs a yes/no question
    # (or Yes/No options), so "Where would you relocate?" never gets "Yes".
    if rule.yes_no and not (_is_yes_no(text) or question.options):
        return None
    if not rule.yes_no and _is_yes_no(text):
        return None
    return rule.answer(question, text, answers)
