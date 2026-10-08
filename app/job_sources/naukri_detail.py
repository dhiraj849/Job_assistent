"""Open one Naukri job detail page and return its HTML. Read only: no clicks.

Logged out on purpose: reading public pages needs no account, and it keeps
this traffic from being tied to the Naukri account we apply with.
"""

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser.naukri_browser import NaukriBrowser
from app.browser.naukri_selectors import JOB_DETAIL_READY

logger = structlog.get_logger(__name__)


class DetailPageUnavailable(Exception):
    """Naukri answered with an error page (retryable: may be temporary)."""


async def fetch_job_page(url: str, headless: bool, timeout_ms: int) -> str:
    browser = NaukriBrowser(headless=headless, timeout_ms=timeout_ms)
    try:
        await browser.start()
        response = await browser.page.goto(url, wait_until="domcontentloaded")
        status = response.status if response else None

        if status == 403:
            # Seen 2026-10-07: Naukri's bot protection blocks headless Chromium.
            raise DetailPageUnavailable(
                f"HTTP 403 from Naukri for {url} (headless={headless}; headless browsers are blocked)"
            )
        if status is not None and status >= 400:
            raise DetailPageUnavailable(f"HTTP {status} from Naukri for {url}")

        try:
            await browser.page.locator(JOB_DETAIL_READY).first.wait_for(state="attached")
        except PlaywrightTimeoutError:
            # Still hand the HTML to the parser: it raises a clear
            # DetailParseError if the JD is really missing (e.g. markup changed).
            logger.warning("job_detail_ready_marker_missing", url=url)

        return await browser.page.content()
    finally:
        await browser.close()
