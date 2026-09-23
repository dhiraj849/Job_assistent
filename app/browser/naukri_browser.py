from playwright.async_api import async_playwright


class NaukriBrowser:

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None

    async def start(self):

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=False
        )

        context = await self.browser.new_context(
            ignore_https_errors=True
        )

        self.page = await context.new_page()

    async def open(self, url: str):

        await self.page.goto(url)

    async def open_naukri(self):

        await self.open(
            "https://www.naukri.com/"
        )

    async def search_jobs(
        self,
        keyword: str,
        location: str
    ):

        await self.page.locator(
            'input[placeholder="Enter skills / designations / companies"]'
        ).fill(keyword)

        await self.page.locator(
            'input[placeholder="Enter location"]'
        ).fill(location)

    async def close(self):

        await self.browser.close()

        await self.playwright.stop()