---
name: sync-docs
description: Update project documentation in docs/ to match code changes. Use after finishing any code change, or when the user asks to sync or update the docs.
---

# Sync docs with code

Goal: docs always describe the code as it is now, using as few tokens as possible.

## Steps
1. Find what changed. Run `git diff --stat HEAD` (and `git status --short` for new
   files). Do NOT read unchanged files.
2. Map each changed path to its doc using the table in CLAUDE.md.
   Skip changes with no doc impact: formatting, tests only, comments, renames of
   private helpers.
3. For each mapped doc:
   - Use `grep -n` to find the relevant section first; read only that section.
   - Edit only the lines that are now wrong or missing. Never rewrite a whole file.
   - Keep Mermaid diagrams in sync if a component, step, table or state changed.
4. If a feature was started or finished, update its status row in
   docs/12-roadmap-and-status.md (Built / In progress / Planned).
5. If a technology was added or replaced, create the next numbered ADR in
   docs/adr/ using docs/adr/ADR-000-template.md (Status, Context, Decision,
   Alternatives, Consequences). Mark any replaced ADR as "Superseded by ADR-XXX".
6. Run `uv run mkdocs build --strict -q` and fix only the errors it reports.
7. Report in 3–5 lines: which docs changed and why.

## Rules
- Never document something that is not in the code. Planned work goes only in
  12-roadmap-and-status.md, marked Planned.
- If docs/ or a mapped file does not exist, say so and ask before creating it.
- Do not touch docs unrelated to the diff.
