"""Fill one ready company-site application, then let me finish and submit it.

For a job whose applications row is ready_for_you (the worker opened the
company site and found a form). Opens that page in a visible browser (no
Naukri click again), opens the job's form if it hides behind an in-page
link, and fills it like --fill-preview: fixed rules, learned answers, AI
suggestions I approve one by one, then a y/N before typing anything.

Then it WAITS: I solve any CAPTCHA / OTP, check the form and click Submit
myself in the browser. This script never clicks Submit. Afterwards it asks
whether I submitted: yes records the job as applied (like mark_applied.py),
no leaves it ready_for_you for another try. Last, it offers each answer I
typed or changed in the browser as a learned answer for next time (y/N each).

Saves artifacts/apply/<job_id>/company-<time>/: 01_filled_form.png,
01_filled_page.png, 01_fill_report.json, 02_after_me.png (personal data:
gitignored, folder 0700).

Usage: uv run python -m scripts.apply_company_site <job_id>
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from app.browser.company_portal import HIDDEN_FORM_STOP, find_job_opener, inspect_page
from app.browser.company_site_page import open_company_page, open_job_form, read_documents, watch_form
from app.browser.naukri_browser import NaukriBrowser
from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.logging_config import setup_logging
from app.models.application import ApplicationOutcome
from app.services.answers_loader import load_answers
from scripts.company_form_cli import ask, current_values, fill_company_form, save_browser_edits

ARTIFACTS_DIR = Path("artifacts/apply")
# Steps I do myself in the browser; they do not stop the fill.
MY_STEPS = ("captcha", "otp")


async def open_form(page, url: str, job_title: str) -> None:
    await open_company_page(page, url)  # a slow "load" event is not fatal
    documents = await read_documents(page)
    if HIDDEN_FORM_STOP in inspect_page(documents[0].url, documents[0].html).hard_stops:
        selector = find_job_opener(documents[0].html, job_title)
        if selector is not None:
            print(f"Opening the form for {job_title!r}: one click on {selector}")
            await open_job_form(page, selector)


async def main(job_id: int) -> int:
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    answers = load_answers(settings.ANSWERS_PATH)
    if answers.contact is None:
        print(f"Needs a 'contact:' block in {settings.ANSWERS_PATH} (see answers.example.yaml).")
        return 1

    async with SessionLocal() as session:
        repo = JobRepository(session)
        job = await repo.get_job(job_id)
        application = await repo.get_application(job_id)
    if job is None or application is None:
        print(f"Job {job_id} not found or never approved.")
        await engine.dispose()
        return 1
    if application.outcome != ApplicationOutcome.READY_FOR_YOU or not application.external_url:
        print(f"Job {job_id} is {application.outcome.value}, not ready_for_you. See: scripts.list_pending")
        await engine.dispose()
        return 1

    url = application.external_url
    print(f"Job {job_id}: {job.title} @ {job.company}")
    print(f"Company site ({application.portal}): {url}")
    if application.human_steps:
        print(f"Seen on the page, for you: {', '.join(application.human_steps)}")

    folder = ARTIFACTS_DIR / str(job_id) / ("company-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    # Visible on purpose: I finish this form myself. No Naukri login needed.
    browser = NaukriBrowser(headless=False, timeout_ms=settings.BROWSER_TIMEOUT_MS, logged_in=False)
    await browser.start()
    try:
        page = browser.page
        await open_form(page, url, job.title)
        filled = await fill_company_form(page, folder, answers, prefix="01", allowed_steps=MY_STEPS)
        if filled is None:
            print("The job stays ready_for_you. Finish it by hand at the URL above, then run "
                  f"scripts.mark_applied {job_id} if you applied.")
            return 1
        try:
            # Submit may leave the page; the watch keeps what I typed until then.
            watch = await watch_form(filled.target, filled.form_index)
        except PlaywrightError:
            watch = None  # learning is a helper; the apply goes on without it

        print("\n######## Your turn, in the browser window")
        print("  1. Check every field (and the screenshot above).")
        print("  2. Tick the consent boxes you agree to, solve any CAPTCHA / OTP.")
        print("  3. Click Submit / Send YOURSELF. This script never clicks it.")
        await ask("Press Enter here when you are done (or gave up)... ")

        try:
            await page.screenshot(path=folder / "02_after_me.png", full_page=True)
        except PlaywrightError:
            pass  # I may have closed the tab; the answer below is what counts.
        values = await current_values(filled, watch)

        submitted = (await ask("Did you submit the application? [y/N] ")).lower() == "y"
    finally:
        await browser.close()

    # What I typed is a good answer whether or not I submitted this time.
    await save_browser_edits(filled, values)

    if not submitted:
        print(f"Not recorded. Job {job_id} stays ready_for_you; run this again later.")
        await engine.dispose()
        return 0

    async with SessionLocal() as session:
        written = await JobRepository(session).record_manual_apply(
            job_id, f"submitted by me on the company site ({application.portal}): {url}"
        )
    await engine.dispose()
    print(f"Job {job_id} recorded as applied." if written else f"Job {job_id} was already applied.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_id", type=int)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.job_id)))
