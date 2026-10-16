"""Search "Next" link on the saved live result pages, in a real (headless) Chromium.

Naukri URLs are served from the fixtures; every other request is blocked, so
nothing leaves the test. Skipped when Playwright's Chromium is missing.
"""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

from app.browser.naukri_browser import JOB_CARD, NaukriBrowser

FIXTURES = Path(__file__).parent.parent / "fixtures" / "naukri"
BASE = "https://www.naukri.com/python-backend-engineer-jobs-in-noida"

# A last page as we expect it: "Next" disabled with no href, like "Previous" on page 1.
LAST_PAGE = """<html><body>
<div class="srp-jobtuple-wrapper"><a class="title" href="https://x/1">Job</a></div>
<div class="styles_pagination__oIvXh">
<a href="/python-backend-engineer-jobs-in-noida-6" class="styles_btn-secondary__2AsIP styles_previous__PobAs"><span>Previous</span></a>
<a disabled="" class="styles_btn-secondary__2AsIP"><span>Next</span></a>
</div></body></html>"""

NO_PAGINATION = '<html><body><div class="srp-jobtuple-wrapper">Job</div></body></html>'


def run_on(html: str, check):
    async def main():
        browser = NaukriBrowser(headless=True, timeout_ms=5000)
        try:
            await browser.start()
        except PlaywrightError as error:
            pytest.skip(f"no Chromium for Playwright: {error}")
        try:
            async def serve(route):
                if route.request.url.startswith(BASE):
                    await route.fulfill(body=html, content_type="text/html")
                else:
                    await route.abort()

            await browser.context.route("**/*", serve)
            await browser.open_results_page(BASE)
            return await check(browser)
        finally:
            await browser.close()

    return asyncio.run(main())


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


async def cards_and_next(browser: NaukriBrowser):
    return await browser.page.locator(JOB_CARD).count(), await browser.next_page_url()


def test_page_1_links_to_page_2():
    assert run_on(fixture("search_page_1.html"), cards_and_next) == (20, f"{BASE}-2")


def test_page_2_links_to_page_3():
    assert run_on(fixture("search_page_2.html"), cards_and_next) == (20, f"{BASE}-3")


def test_disabled_next_means_last_page():
    assert run_on(LAST_PAGE, cards_and_next) == (1, None)


def test_no_pagination_block_means_last_page():
    assert run_on(NO_PAGINATION, cards_and_next) == (1, None)


def test_every_card_on_a_live_page_is_extracted():
    from app.job_sources.naukri_extractor import NaukriExtractor

    async def extract(browser: NaukriBrowser):
        cards = browser.page.locator(JOB_CARD)
        return [await NaukriExtractor().extract_job(cards.nth(i)) for i in range(await cards.count())]

    jobs = run_on(fixture("search_page_1.html"), extract)

    assert len(jobs) == 20
    assert all(job.url and job.title and job.company for job in jobs)


def test_card_without_snippet_is_kept_with_empty_description():
    from app.job_sources.naukri_extractor import NaukriExtractor

    card = """<html><body><div class="srp-jobtuple-wrapper">
    <a class="title" href="https://x/9">Backend Engineer</a>
    <a class="comp-name">Acme</a><span class="loc">Noida</span>
    </div></body></html>"""

    async def extract(browser: NaukriBrowser):
        return await NaukriExtractor().extract_job(browser.page.locator(JOB_CARD).first)

    job = run_on(card, extract)

    assert (job.title, job.description, job.url) == ("Backend Engineer", "", "https://x/9")
