"""Answers I approved for form fields no fixed rule knows (learned_answers.yaml).

An AI suggestion becomes a learned answer only after my y/e in the fill
preview. From then on the same field gets the same answer without any AI
call, so answers stay deterministic and I can edit them by hand. The file
is gitignored (it holds personal details) and lives next to answers.yaml.

A field with a new label can still reuse an answer saved for a related
label ("Total Experience" -> "Years of experience"): similar_answers finds
candidates with local embeddings, and I pick one. Never filled on its own.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LearnedAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Normalised field label -> the answer to type or the option to pick.
    answers: dict[str, str] = Field(default_factory=dict)

    def get(self, label: str) -> str | None:
        return self.answers.get(label_key(label))

    def add(self, label: str, value: str) -> None:
        self.answers[label_key(label)] = value


def label_key(label: str) -> str:
    """"Highest Qualification *:" and "highest qualification" are the same field."""
    text = re.sub(r"[*✱:?]", " ", label.lower())
    return " ".join(text.split())


# Scores of right and wrong matches overlap (bge-small, 2026-10-15: "current
# company" ~ "current employer" 0.85, but ~ "previous company" 0.84), so a
# similar label only ever gives candidates for me to choose from.
SIMILAR_MIN_SCORE = 0.70
SIMILAR_MAX = 3

# Texts -> vectors (app.vector.embedder.Embedder.embed); injected so tests need no model.
Embed = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class SimilarAnswer:
    label: str  # the saved label it was approved for
    value: str
    score: float


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def _fits_kind(value: str, kind: str) -> bool:
    """A typed field only takes a value of its own shape: an address is no
    landline number (zaax.com 2026-10-15: "Landline Number" ~ "current address" 0.71)."""
    if kind == "tel":
        return re.fullmatch(r"[+\d\s().\-]+", value) is not None and sum(c.isdigit() for c in value) >= 6
    if kind == "email":
        return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None
    if kind == "number":
        return re.fullmatch(r"-?\d+(\.\d+)?", value.strip()) is not None
    if kind == "url":
        return value.startswith(("http://", "https://"))
    return True


def _fitting_option(value: str, options: tuple[str, ...]) -> str | None:
    fitting = [o for o in options if " ".join(o.lower().split()) == " ".join(value.lower().split())]
    return fitting[0] if len(fitting) == 1 else None


def similar_answers(
    label: str, learned: LearnedAnswers, embed: Embed, options: tuple[str, ...] = (), kind: str = "text"
) -> list[SimilarAnswer]:
    """Best saved answers for related labels, highest score first.

    With options (a select / radio), only answers that are one of them count,
    returned as the option's own text. A tel / email / number / url field
    only gets values of that shape. One candidate per distinct value.
    """
    key = label_key(label)
    saved = []
    for saved_label, value in learned.answers.items():
        if saved_label == key:
            continue  # the exact label is map_field's job
        if options and (value := _fitting_option(value, options)) is None:
            continue
        if not _fits_kind(value, kind):
            continue
        saved.append((saved_label, value))
    if not saved:
        return []

    vectors = embed([key] + [saved_label for saved_label, _ in saved])
    scored = sorted(
        (SimilarAnswer(saved_label, value, _cosine(vectors[0], vector))
         for (saved_label, value), vector in zip(saved, vectors[1:])),
        key=lambda item: item.score,
        reverse=True,
    )
    best, seen = [], set()
    for item in scored:
        if item.score < SIMILAR_MIN_SCORE or item.value in seen:
            continue
        seen.add(item.value)
        best.append(item)
    return best[:SIMILAR_MAX]


def learned_answers_path(answers_path: Path) -> Path:
    return answers_path.with_name("learned_answers.yaml")


def load_learned(path: Path) -> LearnedAnswers:
    if not path.exists():
        return LearnedAnswers()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return LearnedAnswers.model_validate(data)


def save_learned(path: Path, learned: LearnedAnswers) -> None:
    # Write a temp file and rename: a crash mid-write never leaves half a file.
    tmp = path.with_suffix(".yaml.tmp")
    text = yaml.safe_dump(learned.model_dump(), allow_unicode=True, sort_keys=True)
    tmp.write_text(
        "# Answers I approved for form fields (scripts/inspect_company_site.py --fill-preview).\n"
        "# Edit freely; keys are lowercase field labels.\n" + text,
        encoding="utf-8",
    )
    tmp.replace(path)
