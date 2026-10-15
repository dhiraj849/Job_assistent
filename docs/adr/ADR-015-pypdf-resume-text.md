# ADR-015 — Read the resume PDF's text with pypdf

- **Status:** Accepted
- **Implementation:** Built
- **Date:** 2026-10-15
- **Deciders:** dhiraj

## Context

Company career sites ask fields no fixed rule knows ("Highest qualification", "Current employer").
AI suggestions for them must be grounded: every value must come with a quote from my own documents,
and code checks that the quote really is there. My resume is the main source, and it is a PDF, so
we need its text. The stack must stay free and self-hosted, and the check must be deterministic.

## Decision

Use **pypdf** (pure Python, BSD license) to extract the resume's text layer in
`app/services/resume_text.py`. Whitespace is normalised so quotes can be matched. A PDF with almost
no text (scanned) or a non-PDF resume raises `ResumeTextError`, and the fields simply stay for me.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| pdfminer.six | Very accurate layout | Heavier, slower, more API surface | Layout precision not needed for quotes |
| PyMuPDF | Fast, accurate | AGPL license, native wheels | License |
| Hand-kept `resume.md` | No dependency | Must be kept in sync with the PDF by hand | Drifts from the real resume |
| Let Claude read the PDF with a tool | No dependency | Gives the model file tools; quote check needs the same text in code anyway | Model must stay tool-less (prompt injection) |

## Consequences

- **Positive:** small pure-Python dependency; the same text feeds both the prompt and the quote check.
- **Negative / costs:** scanned resumes give no text (no OCR); multi-column layouts may join lines oddly,
  which can make a correct quote fail the check (the field then stays for me, the safe side).
- **Follow-ups:** none; OCR only if a scanned resume ever matters.
