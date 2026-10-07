"""Inspect the apply flow of one job while logged in. Never applies.

Saves artifacts/inspect/<job_id>/01_job_page.html + .png and prints the apply
button type. With --click (Naukri apply only) it clicks Apply ONCE, waits 5 s,
saves 02_after_click.* and stops: no answers, no submit, no further clicks.

Usage: uv run python -m scripts.inspect_apply_flow <job_id> [--click]
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from app.browser.apply_button import (
    APPLY_BUTTON_CANDIDATES,
    ApplyButtonType,
    classify_apply_button,
)
from app.browser.naukri_browser import NaukriBrowser
from app.browser.session_store import SessionStateError
from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.logging_config import setup_logging

ARTIFACTS_DIR = Path("artifacts/inspect")

# Exact text, so "Applied" / "Apply on company site" can never be clicked.
NAUKRI_APPLY_TEXT = re.compile(r"^\s*apply( now)?\s*$", re.IGNORECASE)


async def snapshot(page, folder: Path, name: str) -> None:
    (folder / f"{name}.html").write_text(await page.content(), encoding="utf-8")
    await page.screenshot(path=folder / f"{name}.png", full_page=True)
    print(f"Saved {folder / name}.html / .png")


async def main(job_id: int, click: bool) -> int:
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    async with SessionLocal() as session:
        job = await JobRepository(session).get_job(job_id)
    await engine.dispose()

    if job is None or not job.url:
        print(f"Job {job_id} not found (or has no URL).")
        return 1

    folder = ARTIFACTS_DIR / str(job_id)
    folder.mkdir(parents=True, exist_ok=True)

    browser = NaukriBrowser(
        headless=settings.BROWSER_HEADLESS,
        timeout_ms=settings.BROWSER_TIMEOUT_MS,
        logged_in=True,
    )
    try:
        await browser.start()
    except SessionStateError as error:
        print(error)
        return 1

    try:
        await browser.page.goto(job.url, wait_until="load")
        # Let client-side rendering finish before we look at the buttons.
        await browser.page.wait_for_timeout(3000)

        if not await browser.is_logged_in():
            print("Session expired. Run: uv run python -m scripts.naukri_login")
            return 1

        await snapshot(browser.page, folder, "01_job_page")

        buttons = browser.page.locator(APPLY_BUTTON_CANDIDATES)
        texts = [text.strip() for text in await buttons.all_inner_texts() if text.strip()]
        button_type = classify_apply_button(texts)

        print(f"Job: {job.title} @ {job.company}")
        print(f"Buttons seen: {texts}")
        print(f"Apply button type: {button_type.value}")

        if not click:
            return 0

        # Safety: only the on-Naukri apply is clicked, and only once.
        if button_type != ApplyButtonType.NAUKRI_APPLY:
            print(f"--click ignored: button type is {button_type.value}, not naukri_apply.")
            return 0

        await buttons.filter(has_text=NAUKRI_APPLY_TEXT).first.click()
        await browser.page.wait_for_timeout(5000)
        await snapshot(browser.page, folder, "02_after_click")
        print("Stopped after the first click. Nothing was answered or submitted.")
        return 0
    finally:
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument(
        "--click", action="store_true", help="click Apply once, then stop"
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args.job_id, args.click)))
