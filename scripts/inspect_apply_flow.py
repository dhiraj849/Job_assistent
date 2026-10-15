"""Inspect the apply flow of one job while logged in.

Saves artifacts/inspect/<job_id>/01_job_page.html + .png and prints the apply
button type. Without --click nothing is clicked.

WARNING --click: it clicks Apply ONCE (Naukri apply only, after a y/N prompt),
waits 5 s, saves 02_after_click.* and stops. For a job without screening
questions that single click IS a real application (seen live on 2026-10-07).
It never answers questions or clicks anything else.

Usage: uv run python -m scripts.inspect_apply_flow <job_id> [--click]
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.browser.apply_button import (
    ApplyButtonType,
    classify_apply_button,
    read_apply_buttons,
)
from app.browser.apply_page import NAUKRI_APPLY_TEXT
from app.browser.naukri_browser import NaukriBrowser
from app.browser.naukri_selectors import APPLY_BUTTONS
from app.browser.session_store import SessionStateError
from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.logging_config import setup_logging

ARTIFACTS_DIR = Path("artifacts/inspect")


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
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)  # personal data: only me

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

        buttons = await read_apply_buttons(browser.page)
        button_type = classify_apply_button(buttons)

        print(f"Job: {job.title} @ {job.company}")
        print(f"Buttons seen (id, text): {buttons}")
        print(f"Apply button type: {button_type.value}")

        if not click:
            return 0

        # Safety: only the on-Naukri apply is clicked, and only once.
        if button_type != ApplyButtonType.NAUKRI_APPLY:
            print(f"--click ignored: button type is {button_type.value}, not naukri_apply.")
            return 0

        # input() blocks; run it in a thread so the browser stays responsive.
        answer = await asyncio.to_thread(
            input,
            "Clicking Apply may SUBMIT a real application if the job has no questions. "
            "Click? [y/N] "
        )
        if answer.strip().lower() != "y":
            print("Not clicked.")
            return 0

        await browser.page.locator(APPLY_BUTTONS).filter(has_text=NAUKRI_APPLY_TEXT).first.click()
        await browser.page.wait_for_timeout(5000)
        await snapshot(browser.page, folder, "02_after_click")
        print("Stopped after the first click. Nothing was answered; check 02_after_click.png "
              "to see if Naukri applied right away.")
        return 0
    finally:
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument(
        "--click", action="store_true", help="click Apply once (may apply for real), then stop"
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args.job_id, args.click)))
