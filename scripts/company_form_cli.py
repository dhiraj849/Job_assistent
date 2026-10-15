"""Shared terminal steps for company-site forms: review unknown fields, fill, save proof.

Used by scripts/inspect_company_site.py (--fill-preview) and
scripts/apply_company_site.py. Interactive on purpose: every AI suggestion,
every answer reused from a related field, the fill itself and every answer
saved from the browser wait for my answer. Nothing here clicks Submit.
"""

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.browser.company_form_mapper import (
    NO_RULE,
    FieldAnswer,
    MappedField,
    ai_forbidden_reason,
    map_form,
)
from app.browser.company_portal import application_form, inspect_page, split_stops
from app.browser.company_site_page import (
    FormWatch,
    fill_form,
    read_documents,
    read_form_values,
    screenshot_form,
)
from app.browser.form_edits import browser_edits
from app.config import settings
from app.llm.form_answerer import ClaudeJsonLLM, Facts, answers_facts, suggest_answers
from app.models.application_answers import ApplicationAnswers
from app.services.learned_answers import (
    LearnedAnswers,
    learned_answers_path,
    load_learned,
    save_learned,
    similar_answers,
)
from app.services.resume_text import ResumeTextError, read_resume_text
from app.vector.embedder import Embedder


@dataclass(frozen=True)
class FilledForm:
    """Where the form was filled and with what, to learn from my browser edits later."""

    target: object  # the Page, or the Frame of an ATS iframe
    form_index: int | None
    url: str
    mapped: list[MappedField]
    # The form's values right after the fill; None if they could not be read.
    baseline: list[dict] | None = None


async def ask(prompt: str) -> str:
    # input() blocks; run it in a thread so the browser stays responsive.
    return (await asyncio.to_thread(input, prompt)).strip()


def _own_value(field, typed: str) -> str | None:
    """What I typed, or the one option it names; None if it fits no option.

    An option may be named by its start ("1-4" for "1-4 Years"), if only one starts so.
    """
    if not typed:
        return None
    if not field.options:
        return typed

    def norm(text: str) -> str:
        return " ".join(text.lower().split())

    exact = [o for o in field.options if norm(o) == norm(typed)]
    matches = exact or [o for o in field.options if norm(o).startswith(norm(typed))]
    if len(matches) != 1:
        print(f"    {typed!r} is not one of {list(field.options)}.")
        return None
    return matches[0]


async def _ask_own(field, prompt: str) -> str | None:
    """My own answer; asks again until it fits the options. Enter leaves it empty."""
    while True:
        typed = await ask(prompt)
        if not typed:
            return None
        if (value := _own_value(field, typed)) is not None:
            return value
        print("    Try again (Enter = leave empty).")


def _similar_for(unknown: list[MappedField], learned: LearnedAnswers) -> dict[int, list]:
    """Answers I approved for related labels, per field (by id). Empty if none saved."""
    if not learned.answers:
        return {}
    try:
        embed = Embedder().embed  # local model, loaded only when there is something to compare
        found = {
            id(m.field): similar_answers(m.field.label, learned, embed, m.field.options, m.field.kind)
            for m in unknown
        }
    except Exception as error:
        # A helper only: without it the fields go to the AI / to me as before.
        print(f"\nNo related learned answers (embedding failed): {error!r}")
        return {}
    return {key: items for key, items in found.items() if items}


async def review_unknown_fields(
    mapped: list[MappedField], answers: ApplicationAnswers, learned: LearnedAnswers
) -> list[MappedField]:
    """For fields no rule knows: answers I gave for related fields, an AI
    suggestion (checked), then my choice for each.

    The AI never sees the fields in AI_FORBIDDEN_WORDS; those are only shown
    when I answered a related field before. Approved and typed answers are
    added to `learned` (saved by the caller).
    """
    unknown = [m for m in mapped if m.reason == NO_RULE]
    similar = _similar_for(unknown, learned)
    ai_fields = [m for m in unknown if ai_forbidden_reason(m.field) is None]
    to_review = [m for m in unknown if ai_forbidden_reason(m.field) is None or id(m.field) in similar]
    if not to_review:
        return mapped

    checked = {}
    if ai_fields:
        try:
            facts = Facts(
                profile=settings.PROFILE_PATH.read_text(encoding="utf-8") if settings.PROFILE_PATH.exists() else "",
                answers=answers_facts(answers),
                resume=read_resume_text(answers.contact.resume_path),
            )
            print(f"\nAsking Claude about {len(ai_fields)} field(s) no rule knows (resume + profile + answers)...")
            for item in await suggest_answers([m.field for m in ai_fields], facts, ClaudeJsonLLM()):
                checked[id(item.field)] = item
        except ResumeTextError as error:
            print(f"\nNo AI suggestions: {error}")
        except Exception as error:
            # The AI is a helper: if it fails, the fields simply stay for me.
            print(f"\nNo AI suggestions (Claude call failed): {error!r}")

    print("\n######## Fields no rule knows: your decision")
    reviewed = {}
    for item in to_review:
        field = item.field
        req = " (required)" if field.required else ""
        print(f"\n{field.label!r}{req}")
        # Key I type -> (value, rule shown in the fill report).
        choices: dict[str, tuple[str, str]] = {}
        for number, found in enumerate(similar.get(id(field), []), start=1):
            print(f"    [{number}] {found.value!r}  (you gave it for {found.label!r}, match {found.score:.2f})")
            choices[str(number)] = (found.value, f"learned for {found.label!r}, chosen by you")
        suggestion = checked.get(id(field))
        if suggestion is not None and suggestion.value is not None:
            print(f"    [y] AI suggests {suggestion.value!r}")
            print(f"        source: \"{suggestion.source_quote}\"")
            choices["y"] = (suggestion.value, "ai, approved by you")
        elif forbidden := ai_forbidden_reason(field):
            print(f"    {forbidden}")
        else:
            print(f"    {suggestion.reason if suggestion is not None else 'no AI suggestion'}")
        if field.options:
            print(f"    options: {list(field.options)}")

        if choices:
            keys = "/".join(choices)
            prompt = f"    [{keys}] use it  [e] type my own  [n] leave empty: "
            choice = (await ask(prompt)).lower()
            # A typo ("1." or a bare value) asks again instead of leaving the field empty.
            while choice not in (*choices, "e", "n"):
                print(f"    Type one of: {keys}, e, n.")
                choice = (await ask(prompt)).lower()
            if choice in choices:
                value, rule = choices[choice]
            elif choice == "e":
                value, rule = await _ask_own(field, "    your answer (Enter = leave empty): "), "typed by you"
            else:
                continue
        else:
            value = await _ask_own(field, "    type your answer (Enter = leave empty): ")
            rule = "typed by you"
        if value is not None:
            learned.add(field.label, value)
            reviewed[id(field)] = MappedField(field=field, answer=FieldAnswer(value=value, rule=rule))

    return [reviewed.get(id(m.field), m) for m in mapped]


async def fill_company_form(
    page, folder: Path, answers: ApplicationAnswers, prefix: str, allowed_steps: tuple[str, ...] = ()
) -> FilledForm | None:
    """Map, review and fill the application form on the page; never submit.

    Saves <prefix>_filled_form.png (the form alone), <prefix>_filled_page.png
    and <prefix>_fill_report.json. Returns what was filled, or None if not.
    allowed_steps: human steps ("captcha", "otp") that do not block filling,
    because I do them myself afterwards.
    """
    # The form may sit in the page itself or in an ATS iframe (Greenhouse embed).
    documents = await read_documents(page)
    report, target = inspect_page(documents[0].url, documents[0].html), page
    for doc in documents:
        doc_report = inspect_page(doc.url, doc.html)
        if application_form(doc_report.fields):
            report, target = doc_report, doc.frame
            break
    steps, blocking = split_stops(report.hard_stops)
    blocking += [f"{step} on the page" for step in steps if step not in allowed_steps]
    if blocking:
        print("Not filled, hard stops: " + "; ".join(blocking))
        return None
    form = application_form(report.fields)
    if not form:
        print("Not filled: no visible application form on this page.")
        return None

    learned_path = learned_answers_path(settings.ANSWERS_PATH)
    learned = load_learned(learned_path)
    mapped = await review_unknown_fields(map_form(form, answers, learned), answers, learned)
    if learned.answers != load_learned(learned_path).answers:
        save_learned(learned_path, learned)
        print(f"Saved your approved answers to {learned_path} (used next time without AI).")

    print("\nREQ  FIELD  ->  VALUE (rule)  |  or why it stays empty")
    for item in mapped:
        req = "*" if item.field.required else " "
        if item.answer:
            print(f"  {req}  {item.field.label!r}  ->  {item.answer.value!r} ({item.answer.rule})")
        else:
            print(f"  {req}  {item.field.label!r}  ->  (empty) {item.reason}")
    missing = [m.field.label for m in mapped if m.field.required and m.field.visible and not m.answer]
    if missing:
        print(f"Required and left for you: {missing}")

    answer = await asyncio.to_thread(
        input,
        f"Type these values into the form on {page.url}? Nothing is submitted. [y/N] ",
    )
    if answer.strip().lower() != "y":
        print("Not filled.")
        return None

    results = await fill_form(target, form[0].form, mapped)
    for result in results:
        print(f"  {result.status:<8}  {result.label!r} = {result.value!r}")

    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    await screenshot_form(target, folder / f"{prefix}_filled_form.png")
    await page.screenshot(path=folder / f"{prefix}_filled_page.png", full_page=True)
    data = {
        "url": page.url,
        "fields": [
            {
                "label": m.field.label,
                "name": m.field.name,
                "required": m.field.required,
                "value": m.answer.value if m.answer else None,
                "rule": m.answer.rule if m.answer else None,
                "reason": m.reason,
            }
            for m in mapped
        ],
        "fill_results": [asdict(result) for result in results],
    }
    (folder / f"{prefix}_fill_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved {folder / f'{prefix}_filled_form.png'}, {prefix}_filled_page.png, {prefix}_fill_report.json")
    baseline = await read_form_values(target, form[0].form)
    return FilledForm(target=target, form_index=form[0].form, url=target.url, mapped=mapped, baseline=baseline)


async def current_values(filled: FilledForm, watch: FormWatch | None = None) -> list[dict] | None:
    """The form's values as I left them in the browser.

    The watch's last report wins (taken on my last change and on Submit):
    after Submit the form may be gone (navigated away) or cleared on the
    same URL (zaax.com 2026-10-15: fetch() then form.reset()). Without a
    report, read the form now if the page is still the filled one.
    """
    if watch is not None and watch.latest:
        return watch.latest
    if filled.target.url == filled.url:
        return await read_form_values(filled.target, filled.form_index)
    return None


async def save_browser_edits(filled: FilledForm, values: list[dict] | None) -> None:
    """Offer what I typed or changed in the browser as learned answers, y/N each."""
    if not values:
        print("Could not read the form from the browser; nothing new to learn.")
        return
    learned_path = learned_answers_path(settings.ANSWERS_PATH)
    learned = load_learned(learned_path)
    edits = browser_edits(filled.mapped, values, learned, filled.baseline)
    for edit in (e for e in edits if e.fixed_rule):
        print(f"  {edit.field.label!r}: you changed it, but it comes from answers.yaml "
              f"({edit.fixed_rule}). Edit answers.yaml if it should change for good.")
    new = [e for e in edits if not e.fixed_rule]
    if not new:
        print("No new answers from the browser to save.")
        return

    print("\n######## Answers you gave in the browser")
    for edit in new:
        was = f" (I had filled {edit.before!r})" if edit.before is not None else ""
        question = f"  Save {edit.field.label!r} = {edit.value!r}{was} for next time? [y/N] "
        if (await ask(question)).lower() == "y":
            learned.add(edit.field.label, edit.value)
    if learned.answers != load_learned(learned_path).answers:
        save_learned(learned_path, learned)
        print(f"Saved to {learned_path}.")
