import structlog
from playwright.async_api import Browser, Page, Playwright, async_playwright

logger = structlog.get_logger(__name__)

NAUKRI_URL = "https://www.naukri.com/"
KEYWORD_INPUT = 'input[placeholder="Enter skills / designations / companies"]'
LOCATION_INPUT = 'input[placeholder="Enter location"]'
JOB_CARD = ".srp-jobtuple-wrapper"


class NaukriBrowser:

    def __init__(self, headless: bool = False, timeout_ms: int = 20000):
        self.headless = headless
        self.timeout_ms = timeout_ms

        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def start(self) -> None:
        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=self.headless
        )

        self.page = await self.browser.new_page()

        self.page.set_default_timeout(self.timeout_ms)

    async def open_naukri(self) -> None:
        await self.page.goto(NAUKRI_URL)

    async def search_jobs(self, keyword: str, location: str) -> None:
        await self.page.locator(KEYWORD_INPUT).fill(keyword)
        await self.page.locator(LOCATION_INPUT).fill(location)

        await self.page.get_by_text("Search", exact=True).click()

        await self.page.wait_for_selector(JOB_CARD)

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()

        if self.playwright is not None:
            await self.playwright.stop()