"""Open one job detail page and save its HTML, so we can find the description selector.

Run: uv run python -m scripts.inspect_job_page
"""

import asyncio
from pathlib import Path

from sqlalchemy import text

from app.browser.naukri_browser import NaukriBrowser
from app.config import settings
from app.db.database import SessionLocal, engine

OUTPUT_PATH = Path("/tmp/naukri_job_page.html")


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT url FROM jobs LIMIT 1"))
        url = result.scalar_one()

    print(f"Opening {url}")

    browser = NaukriBrowser(headless=False, timeout_ms=settings.BROWSER_TIMEOUT_MS)
    try:
        await browser.start()
        await browser.page.goto(url, wait_until="load")
        # Give client-side rendering a moment to fill in the description
        await browser.page.wait_for_timeout(3000)

        OUTPUT_PATH.write_text(await browser.page.content(), encoding="utf-8")
        print(f"Saved HTML to {OUTPUT_PATH}")
    finally:
        await browser.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
