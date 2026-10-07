import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.browser.naukri_selectors import LOGGED_IN_MARKER
from app.browser.session_store import load_state

logger = structlog.get_logger(__name__)

NAUKRI_URL = "https://www.naukri.com/"
KEYWORD_INPUT = 'input[placeholder="Enter skills / designations / companies"]'
LOCATION_INPUT = 'input[placeholder="Enter location"]'
JOB_CARD = ".srp-jobtuple-wrapper"
NAUKRI_LOGIN_URL = "https://www.naukri.com/nlogin/login"


class NaukriBrowser:

    def __init__(
        self,
        headless: bool = False,
        timeout_ms: int = 20000,
        logged_in: bool = False,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        # True: reuse the saved, encrypted login session (see session_store).
        self.logged_in = logged_in

        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> None:
        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=self.headless
        )

        # A fresh context per run; in logged-in mode it starts with the saved cookies.
        storage_state = load_state() if self.logged_in else None
        self.context = await self.browser.new_context(storage_state=storage_state)

        self.page = await self.context.new_page()

        self.page.set_default_timeout(self.timeout_ms)

    async def open_naukri(self) -> None:
        await self.page.goto(NAUKRI_URL)

    async def search_jobs(self, keyword: str, location: str) -> None:
        await self.page.locator(KEYWORD_INPUT).fill(keyword)
        await self.page.locator(LOCATION_INPUT).fill(location)

        await self.page.get_by_text("Search", exact=True).click()

        await self.page.wait_for_selector(JOB_CARD)

    async def is_logged_in(self, timeout_ms: int = 5000) -> bool:
        """True if the Naukri header shows the logged-in avatar/profile link."""
        if not self.page.url.startswith(NAUKRI_URL):
            await self.open_naukri()
        try:
            await self.page.locator(LOGGED_IN_MARKER).first.wait_for(
                state="visible", timeout=timeout_ms
            )
            return True
        except PlaywrightTimeoutError:
            return False

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()

        if self.playwright is not None:
            await self.playwright.stop()