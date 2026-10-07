"""Log in to Naukri by hand once and save the session, encrypted.

Opens a HEADED browser at the login page. You log in yourself (password, OTP...),
then press Enter here. The session is saved to NAUKRI_STATE_PATH only if the
logged-in header is visible.

Usage: uv run python -m scripts.naukri_login
"""

import asyncio
import sys

from app.browser.naukri_browser import NAUKRI_LOGIN_URL, NaukriBrowser
from app.browser.session_store import SessionStateError, check_key, save_state
from app.config import settings
from app.logging_config import setup_logging


async def main() -> int:
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    # Check the key first, so a manual login (OTP etc.) is never wasted.
    try:
        check_key()
    except SessionStateError as error:
        print(error)
        return 1

    # Always headed: a human has to type the password / OTP.
    browser = NaukriBrowser(headless=False, timeout_ms=settings.BROWSER_TIMEOUT_MS)
    try:
        await browser.start()
        await browser.page.goto(NAUKRI_LOGIN_URL)

        # input() blocks; run it in a thread so the browser stays responsive.
        await asyncio.to_thread(
            input, "Log in in the browser window, then press Enter here... "
        )

        if not await browser.is_logged_in():
            print("Not logged in (profile avatar not found). Nothing saved.")
            return 1

        save_state(await browser.context.storage_state())
        print(f"Logged in. Session saved (encrypted) to {settings.NAUKRI_STATE_PATH}")
        return 0
    finally:
        await browser.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
