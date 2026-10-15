"""Save Naukri search result pages 1 and 2 as test fixtures, to learn how Naukri paginates.

Run: uv run python -m scripts.inspect_search_page

Read only: one search (JOB_SEARCH_KEYWORD / JOB_SEARCH_LOCATION), then page 2.
No other clicks. Writes tests/fixtures/naukri/search_page_<n>.html, trimmed to
the job cards + the pagination block, and prints the URL, the raw pagination
markup and the card count per page.
"""

import asyncio
from pathlib import Path

from app.browser.naukri_browser import JOB_CARD, NaukriBrowser
from app.config import settings

FIXTURES = Path("tests/fixtures/naukri")
PAGE_DELAY_SECONDS = 3.0

# We don't know Naukri's pagination markup yet, so find it two ways:
# a class with "pagination" in it, or the parent of a "Next" link/button.
FIND_PAGINATION_JS = """
() => {
    const byClass = document.querySelector("[class*='pagination' i]");
    if (byClass) return byClass.outerHTML;
    const next = [...document.querySelectorAll("a, button, span")]
        .find(el => el.textContent.trim().toLowerCase() === "next");
    return next ? next.parentElement.outerHTML : null;
}
"""

# The element a user would press for page 2: its tag, href and attributes.
FIND_NEXT_JS = """
() => {
    const next = [...document.querySelectorAll("a, button, span")]
        .find(el => el.textContent.trim().toLowerCase() === "next");
    if (!next) return null;
    const link = next.closest("a") || next;
    return {
        tag: link.tagName,
        href: link.getAttribute("href"),
        attrs: Object.fromEntries([...link.attributes].map(a => [a.name, a.value])),
    };
}
"""

# "1 - 20 of 1234 ..." style counter, if Naukri shows one.
FIND_COUNT_JS = """
() => {
    const el = [...document.querySelectorAll("span, div")]
        .find(e => e.children.length === 0 && /\\d+\\s*-\\s*\\d+\\s+of\\s+\\d+/i.test(e.textContent));
    return el ? el.outerHTML : null;
}
"""


async def capture(browser: NaukriBrowser, page_no: int) -> dict | None:
    """Print what this page shows, save the trimmed fixture, return the Next element."""
    page = browser.page
    await page.wait_for_selector(JOB_CARD)

    cards = await page.locator(JOB_CARD).evaluate_all("els => els.map(e => e.outerHTML)")
    pagination = await page.evaluate(FIND_PAGINATION_JS)
    counter = await page.evaluate(FIND_COUNT_JS)
    next_element = await page.evaluate(FIND_NEXT_JS)

    print(f"\n=== Page {page_no} ===")
    print(f"URL: {page.url}")
    print(f"Cards: {len(cards)}")
    print(f"Counter: {counter}")
    print(f"Next element: {next_element}")
    print(f"Pagination block:\n{pagination}")

    parts = [f"<!-- url: {page.url} -->", *cards, pagination or "<!-- no pagination block found -->"]
    path = FIXTURES / f"search_page_{page_no}.html"
    path.write_text("<html><body>\n" + "\n".join(parts) + "\n</body></html>\n", encoding="utf-8")
    print(f"Saved {path}")

    return next_element


async def main() -> None:
    # Headed on purpose: Naukri answers 403 to headless Chromium.
    browser = NaukriBrowser(headless=False, timeout_ms=settings.BROWSER_TIMEOUT_MS)
    await browser.start()
    try:
        await browser.open_naukri()
        await browser.search_jobs(settings.JOB_SEARCH_KEYWORD, settings.JOB_SEARCH_LOCATION)

        next_element = await capture(browser, 1)
        if next_element is None:
            print("\nNo Next element on page 1; stopping.")
            return

        await asyncio.sleep(PAGE_DELAY_SECONDS)

        # Prefer a plain navigation to the Next href (no click). Only a JS-only
        # button with no href gets clicked, and that is the single allowed click.
        href = next_element["href"]
        if href and not href.startswith(("#", "javascript")):
            print(f"\nGoing to page 2 via href: {href}")
            await browser.page.goto(href if href.startswith("http") else f"https://www.naukri.com{href}")
        else:
            print("\nNext has no usable href; clicking it once.")
            await browser.page.get_by_text("Next", exact=True).first.click()
            await browser.page.wait_for_load_state("networkidle")

        await capture(browser, 2)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
