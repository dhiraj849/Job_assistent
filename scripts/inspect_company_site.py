"""Inspect the company career site behind a Naukri "Apply on company site" job.

Opens each job (logged in, one at a time, DETAIL_PAGE_DELAY_SECONDS apart)
and prints its apply button type. Without --click nothing is clicked, so a
batch safely finds the company-site jobs.

With --click, for a company-site job and after a y/N prompt, it clicks
"Apply on company site" ONCE, follows it to the company page and saves,
under artifacts/inspect/company/<job_id>/:
  01_job_page.html/.png, 02_company_site.html/.png, 02_<frame>.html (iframes),
  02_report.json (portal type, fields, hard stops per document).
If the application form is hidden and exactly one in-page link opens it for
this job's exact title (e.g. a careers list with a shared modal), it clicks
that link once and saves the same again as 03_*, plus 03_form.png: the form
alone (a full-page screenshot cuts off a form inside a scrollable modal).
If the page has no form at all and this job's own "Apply" link (under a
heading that is exactly the title) goes to another page of the same site
(e.g. one shared /submit-resume/ form), it loads that page and saves 03_*.
Then prints the detected portal type, hard stops and fields, and at the end
a one-line summary per job (so a batch finds the company-site jobs).

WARNING --click: Naukri marks the job "Applied" as soon as "Apply on company
site" is clicked, even if nothing is submitted on the company site (seen
live on 2026-10-15, job 455). The click and the company URL are recorded on
the job (jobs.company_site_opened_at / company_site_url), so the apply flow
later checks that URL directly instead of trusting Naukri's "Applied".
To look at a company page without any click, use --url.

Without --fill-preview nothing is typed, uploaded or submitted. The clicks:
Naukri's own button (only with --click) and, at most once, an in-page link
that only opens the form (no href, "#" or javascript:).

--fill-preview (after a y/N prompt): fills the application form from
answers.yaml (contact block + screening answers) with the deterministic
mapper, reads every value back, and saves 04_filled_form.png (the form),
04_filled_page.png and 04_fill_report.json, so you can check each value.
It NEVER clicks Submit/Send; the browser closes right after, so the form is
never sent. Checkboxes (consents) and fields without a sure answer stay
empty and are listed. Hidden fields (spam traps) are never filled.
Fields no rule knows: Claude suggests a value from your resume, profile.yaml
and answers.yaml (with the exact quote it came from; the code rejects any
quote not in those files), and you decide each one: y / n / e (type your
own). What you accept is saved in learned_answers.yaml and reused without
AI next time. Claude never answers consents, money, notice, IDs, protected
characteristics or legal declarations. Note:
the values are typed into the company's page; a site's own scripts
(analytics) could read them even without a submit.
Use the saved HTML as test fixtures (tests/fixtures/company_sites/).

Usage:
  uv run python -m scripts.inspect_company_site <job_id> [<job_id> ...] [--click]
  uv run python -m scripts.inspect_company_site --url https://jobs.lever.co/acme/123/apply [--title "..."]
  uv run python -m scripts.inspect_company_site --url https://kmgus.com/careers/ --title "Python Developer" --fill-preview
  uv run python -m scripts.inspect_company_site --html saved.html --url <the page's URL>
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from app.browser.apply_button import ApplyButtonType, classify_apply_button, read_apply_buttons
from app.browser.company_portal import (
    HIDDEN_FORM_STOP,
    PageReport,
    application_form,
    find_job_opener,
    find_job_page_link,
    inspect_page,
)
from app.browser.company_site_page import (
    FrameDocument,
    follow_company_site_button,
    open_job_form,
    open_company_page,
    read_documents,
    screenshot_form,
)
from app.browser.naukri_browser import NaukriBrowser
from app.browser.session_store import SessionStateError
from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.logging_config import setup_logging
from app.models.application_answers import ApplicationAnswers
from app.models.job import Job
from app.services.answers_loader import load_answers
from scripts.company_form_cli import ask, current_values, fill_company_form, save_browser_edits

ARTIFACTS_DIR = Path("artifacts/inspect/company")


async def snapshot(page, folder: Path, name: str) -> None:
    (folder / f"{name}.html").write_text(await page.content(), encoding="utf-8")
    await page.screenshot(path=folder / f"{name}.png", full_page=True)
    print(f"Saved {folder / name}.html / .png")


def print_report(name: str, report: PageReport) -> None:
    print(f"\n== {name}: {report.url}")
    print(f"Portal type: {report.portal.value}")
    print("Hard stops: " + ("; ".join(report.hard_stops) if report.hard_stops else "none seen"))
    if not report.fields:
        print("Fields: none")
        return
    print(f"Fields ({len(report.fields)}):  REQ (h = hidden)  KIND  LABEL  [name / autocomplete]  options")
    for f in report.fields:
        req = ("*" if f.required else " ") + (" " if f.visible else "h")
        extra = f"  options={list(f.options)}" if f.options else ""
        print(f"  {req:>3}  {f.kind:<10}  {f.label!r}  [{f.name} / {f.autocomplete}]{extra}")


def report_documents(
    documents: list[FrameDocument], folder: Path | None, prefix: str = "02"
) -> PageReport:
    """Print and save the report of each document; return the one most likely holding the form."""
    reports = {doc.name: inspect_page(doc.url, doc.html) for doc in documents}
    for doc in documents:
        print_report(doc.name, reports[doc.name])

    # The form usually sits in the document with the most fields (page or ATS iframe).
    best = max(reports, key=lambda name: len(reports[name].fields))
    print(f"\nMost fields in: {best} ({reports[best].portal.value}, {len(reports[best].fields)} fields)")

    if folder is not None:
        for doc in documents:
            if doc.name != "page":
                (folder / f"{prefix}_{doc.name}.html").write_text(doc.html, encoding="utf-8")
        data = {name: asdict(report) for name, report in reports.items()}
        report_path = folder / f"{prefix}_report.json"
        report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Saved {report_path}")
    return reports[best]


async def fill_preview(page, folder: Path, answers: ApplicationAnswers) -> None:
    """Fill the application form on the page (never submit) and save screenshots to check."""
    print("\n######## Fill preview")
    filled = await fill_company_form(page, folder, answers, prefix="04")
    if filled is None:
        return
    if not settings.BROWSER_HEADLESS:
        # Teach it: what I fix or fill in by hand is offered as an answer for next time.
        print("\nYou may fix or fill fields in the browser now; I offer them as answers for next time.")
        print("Do NOT click Submit: this is only a preview.")
        await ask("Press Enter here when done... ")
        await save_browser_edits(filled, await current_values(filled))
    print("Not submitted. The browser closes now, so the form is never sent.")


async def inspect_company_page(
    page, folder: Path, job_title: str, answers: ApplicationAnswers | None
) -> PageReport:
    """Report the company page; if its form is hidden behind this job's own
    in-page "Apply" link, click that link once and report again. With
    answers, also run the fill preview."""
    best = await _inspect_and_open(page, folder, job_title)
    if answers is not None:
        await fill_preview(page, folder, answers)
    return best


async def _inspect_and_open(page, folder: Path, job_title: str) -> PageReport:
    # Read first: it marks hidden fields, so the saved HTML carries the marker.
    documents = await read_documents(page)
    await snapshot(page, folder, "02_company_site")
    best = report_documents(documents, folder)
    if HIDDEN_FORM_STOP not in best.hard_stops:
        return await _open_job_page(page, folder, job_title, documents, best)

    selector = find_job_opener(documents[0].html, job_title)
    if selector is None:
        print(f"\nForm is hidden and no single in-page link opens it for {job_title!r}; not clicked.")
        return best
    print(f"\nOpening the hidden form for {job_title!r}: one click on {selector}")
    await open_job_form(page, selector)
    documents = await read_documents(page)
    await snapshot(page, folder, "03_form_opened")
    if await screenshot_form(page, folder / "03_form.png"):
        print(f"Saved {folder / '03_form.png'} (the form alone; the full page can miss it in a modal)")
    return report_documents(documents, folder, prefix="03")


async def _open_job_page(page, folder: Path, job_title: str, documents, best: PageReport) -> PageReport:
    """A careers list with no form: open this job's own "Apply" page, if it links to one."""
    if application_form(best.fields):
        return best
    link = find_job_page_link(documents[0].html, documents[0].url, job_title)
    if link is None:
        return best
    print(f"\nNo form here; opening this job's own apply page (a page load, nothing sent): {link}")
    await open_company_page(page, link)
    documents = await read_documents(page)
    await snapshot(page, folder, "03_job_page")
    return report_documents(documents, folder, prefix="03")


async def load_jobs(job_ids: list[int]) -> dict[int, Job | None]:
    async with SessionLocal() as session:
        repo = JobRepository(session)
        jobs = {job_id: await repo.get_job(job_id) for job_id in job_ids}
    await engine.dispose()
    return jobs


class SessionExpired(Exception):
    """Stop the whole run: every later job would fail the same way."""


async def record_click(job_id: int, url: str | None = None) -> None:
    async with SessionLocal() as session:
        await JobRepository(session).mark_company_site_opened(job_id, url)
        await session.commit()


async def confirm_click(job_id: int) -> bool:
    # input() blocks; run it in a thread so the browser stays responsive.
    answer = await asyncio.to_thread(
        input,
        f"Job {job_id}: clicking 'Apply on company site' makes Naukri mark it APPLIED "
        "(nothing is submitted anywhere). Click? [y/N] ",
    )
    return answer.strip().lower() == "y"


async def inspect_job(
    browser: NaukriBrowser, job_id: int, job: Job | None, click: bool, answers: ApplicationAnswers | None
) -> str:
    """Job page -> (only for a company-site button) company page. Returns a one-line result."""
    print(f"\n######## Job {job_id}")
    if job is None or not job.url:
        print("Not found (or has no URL).")
        return "not found"

    folder = ARTIFACTS_DIR / str(job_id)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    await browser.page.goto(job.url, wait_until="load")
    # Let client-side rendering finish before we look at the buttons.
    await browser.page.wait_for_timeout(3000)
    if not await browser.is_logged_in():
        raise SessionExpired("Session expired. Run: uv run python -m scripts.naukri_login")
    await snapshot(browser.page, folder, "01_job_page")

    button = classify_apply_button(await read_apply_buttons(browser.page))
    print(f"Job: {job.title} @ {job.company}")
    print(f"Apply button type: {button.value}")
    if button != ApplyButtonType.COMPANY_SITE:
        print("Not a company-site job; nothing clicked.")
        return button.value
    if not click:
        print("Company-site job; not clicked (needs --click).")
        return "company_site (not clicked)"
    if not await confirm_click(job_id):
        print("Not clicked.")
        return "company_site (not clicked)"

    # Recorded first (issue #18): Naukri shows the job as "Applied" from now on,
    # and the apply flow must know that was our click, not an application.
    await record_click(job_id)
    page = await follow_company_site_button(browser.context, browser.page)
    await record_click(job_id, page.url)
    try:
        print(f"Company site URL: {page.url}")
        best = await inspect_company_page(page, folder, job.title, answers)
        return f"company_site -> {best.portal.value} ({len(best.fields)} fields) {page.url}"
    finally:
        # A new tab per job would pile up; the Naukri tab is reused.
        if page != browser.page:
            await page.close()


async def main(
    job_ids: list[int], url: str | None, title: str, click: bool, preview: bool
) -> int:
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    answers = None
    if preview:
        # Fail before opening any browser if the answers cannot be used.
        answers = load_answers(settings.ANSWERS_PATH)
        if answers.contact is None:
            print(f"--fill-preview needs a 'contact:' block in {settings.ANSWERS_PATH} "
                  "(see answers.example.yaml).")
            return 1
    jobs = await load_jobs(job_ids) if job_ids else {}

    # Logged in only when we go through Naukri; a direct --url needs no session.
    browser = NaukriBrowser(
        headless=settings.BROWSER_HEADLESS,
        timeout_ms=settings.BROWSER_TIMEOUT_MS,
        logged_in=bool(job_ids),
    )
    try:
        await browser.start()
    except SessionStateError as error:
        print(error)
        return 1

    try:
        if url:
            folder = ARTIFACTS_DIR / ("url-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            await open_company_page(browser.page, url)
            print(f"Company site URL: {browser.page.url}")
            await inspect_company_page(browser.page, folder, title, answers)
            print("\nNothing was submitted." if answers else "\nNothing was typed or submitted.")
            return 0

        results: dict[int, str] = {}
        for number, job_id in enumerate(job_ids):
            if number:
                # Same pacing as detail-page fetches: one page at a time, never a burst.
                await asyncio.sleep(settings.DETAIL_PAGE_DELAY_SECONDS)
            try:
                results[job_id] = await inspect_job(browser, job_id, jobs[job_id], click, answers)
            except SessionExpired as error:
                print(error)
                return 1
            except PlaywrightError as error:
                # One broken page (timeout, TLS error) must not end the batch.
                print(f"Error: {error}".splitlines()[0])
                results[job_id] = "error: " + str(error).splitlines()[0]

        print("\n######## Summary")
        for job_id, result in results.items():
            print(f"{job_id:>6}  {result}")
        print("\nNothing was submitted." if answers else "\nNothing was typed or submitted.")
        return 0
    finally:
        await browser.close()


def main_offline(html_path: Path, url: str) -> int:
    """Re-run detection on a saved page, no browser (e.g. after editing selectors)."""
    report_documents([FrameDocument("page", url, html_path.read_text(encoding="utf-8"))], None)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_ids", type=int, nargs="*", help="one or more job ids")
    parser.add_argument("--url", help="open this URL directly (no Naukri, no click)")
    parser.add_argument("--html", type=Path, help="saved HTML to analyse offline (needs --url)")
    parser.add_argument(
        "--click", action="store_true",
        help="click 'Apply on company site' (y/N per job); Naukri then marks the job Applied",
    )
    parser.add_argument(
        "--fill-preview", action="store_true",
        help="fill the form from answers.yaml (y/N), screenshot it, never submit",
    )
    parser.add_argument("--title", default="", help="job title, with --url: opens that job's hidden form")
    args = parser.parse_args()

    if args.html:
        if not args.url:
            parser.error("--html needs --url (detection uses the page's URL)")
        sys.exit(main_offline(args.html, args.url))
    if bool(args.job_ids) == bool(args.url):
        parser.error("give job ids or --url, not both")
    if args.click and not args.job_ids:
        parser.error("--click needs job ids")
    if args.fill_preview and args.job_ids and not args.click:
        parser.error("--fill-preview with job ids needs --click (or use --url)")
    sys.exit(asyncio.run(main(args.job_ids, args.url, args.title, args.click, args.fill_preview)))
