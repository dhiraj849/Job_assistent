"""Save Naukri job detail pages as test fixtures. Read only: opens pages, no clicks.

Run: uv run python -m scripts.inspect_job_page 34 37 39   (job ids from the jobs table)

Writes tests/fixtures/naukri/job_detail_<id>.html, trimmed to what the detail
parser reads (JobPosting JSON-LD + the JD section), and prints what
parse_job_detail finds, so a markup change shows up right away.
"""

import argparse
import asyncio
import re
from pathlib import Path

from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.job_sources.naukri_detail import fetch_job_page
from app.job_sources.naukri_detail_parser import DetailParseError, parse_job_detail

FIXTURES = Path("tests/fixtures/naukri")
JD_SECTION_START = re.compile(r'<section class="styles_job-desc-container')
JSON_LD = re.compile(r'<script type="application/ld\+json">.*?</script>', re.S)


def trim(html: str) -> str:
    """Keep the JSON-LD blocks and the JD <section>; the full page is ~260 KB."""
    parts = JSON_LD.findall(html)

    start = JD_SECTION_START.search(html)
    if start:
        # Walk to the matching </section> (sections can nest).
        depth, pos = 0, start.start()
        for tag in re.finditer(r"<(/?)section\b", html[pos:]):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                end = html.index(">", pos + tag.start()) + 1
                parts.append(html[start.start():end])
                break

    return "<html><body>\n" + "\n".join(parts) + "\n</body></html>\n"


async def main(job_ids: list[int]) -> None:
    async with SessionLocal() as session:
        repository = JobRepository(session)
        urls = {job_id: (await repository.get_job(job_id)).url for job_id in job_ids}
    await engine.dispose()

    for i, (job_id, url) in enumerate(urls.items()):
        if i:
            await asyncio.sleep(settings.DETAIL_PAGE_DELAY_SECONDS)
        print(f"Opening job {job_id}: {url}")
        # Headed on purpose: Naukri answers 403 to headless Chromium.
        html = await fetch_job_page(url, headless=False, timeout_ms=settings.BROWSER_TIMEOUT_MS)

        path = FIXTURES / f"job_detail_{job_id}.html"
        path.write_text(trim(html), encoding="utf-8")
        try:
            page = parse_job_detail(html)
            print(f"  saved {path}: {len(page.description)} chars, source={page.details.source}")
        except DetailParseError as error:
            print(f"  saved {path}, but parsing FAILED: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("job_ids", type=int, nargs="+")
    asyncio.run(main(parser.parse_args().job_ids))
