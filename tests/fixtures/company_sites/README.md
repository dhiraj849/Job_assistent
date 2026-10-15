# Company career site fixtures

Saved pages for `tests/browser/test_company_portal.py` (no live site in tests).

- `synthetic_*.html`: hand-written from public ATS markup (Greenhouse, Lever,
  Workday) before any live sample existed. Small on purpose: each shows one
  case. Replace or extend with real pages as they are collected.
- Real pages: save with `uv run python -m scripts.inspect_company_site <job_id>`
  and copy `02_company_site.html` (or the `02_frame_*.html` holding the form)
  here as `<portal>_<company>.html`. Remove any personal data first.

Live pages so far:

- `generic_kmgus.html`: https://kmgus.com/careers/ (job 455, 2026-10-15). WordPress
  careers list; each job's "Apply" link opens one shared modal with a Contact Form 7
  resume form, plus an Akismet honeypot and an invisible reCAPTCHA. Only public company
  emails in it. Hidden-field markers (`data-jobagent-hidden`) were added afterwards by
  running `read_documents` on the saved page, as the inspector now does live.

- `generic_kmgus_form_open.html`: the same page saved live after the inspector clicked
  `Enquiry('Python Developer')` once (2026-10-15, `--url ... --title`). Modal open, hidden
  `ServiceName` field set to the job title, nothing typed.

The URL each page was loaded from is in the test (detection uses it).
