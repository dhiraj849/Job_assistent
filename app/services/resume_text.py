"""Plain text of the resume PDF, for grounding AI form answers.

pypdf only reads a PDF's text layer: a scanned (image-only) resume gives
no text, and that fails loudly instead of letting the AI answer from nothing.
"""

from pathlib import Path

from pypdf import PdfReader

# Fewer characters than this is a scanned or broken PDF, not a resume.
MIN_RESUME_CHARS = 200


class ResumeTextError(Exception):
    """The resume has no usable text (not a PDF, scanned, or unreadable)."""


def read_resume_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        raise ResumeTextError(f"only a .pdf resume can be read for AI answers: {path.name}")
    try:
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as error:  # pypdf raises many types for broken files
        raise ResumeTextError(f"cannot read {path.name}: {error}") from None
    # One space between words, one line per line: quotes are matched on this.
    lines = (" ".join(line.split()) for line in text.splitlines())
    text = "\n".join(line for line in lines if line)
    if len(text) < MIN_RESUME_CHARS:
        raise ResumeTextError(f"{path.name} has almost no text (scanned PDF?)")
    return text
