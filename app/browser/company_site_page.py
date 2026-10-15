"""The browser side of a company career site: follow the Naukri button, read the page.

Thin Playwright code, no decisions (those live in company_portal.py).
Nothing here types into a field or submits anything.
"""

from dataclasses import dataclass, field
from pathlib import Path

import structlog
from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.browser.company_site_selectors import HIDDEN_FIELD_ATTR
from app.browser.naukri_selectors import COMPANY_SITE_BUTTON

logger = structlog.get_logger(__name__)

# How long a click may take to open the new tab before we treat it as a
# same-tab redirect.
NEW_TAB_TIMEOUT_MS = 10_000
# A modal / tab opening after an in-page click is quick; no page load.
OPEN_FORM_WAIT_MS = 2_000
# Career sites render forms client-side (and some redirect twice); give
# them time before reading.
SETTLE_MS = 5_000


# Marks each field the person cannot see, so the pure parser (which has no
# CSS) can tell. Only an attribute in our local copy of the DOM; nothing is
# sent to the site. Zero size covers a hidden parent (CF7 honeypots sit in a
# display:none <p>); negative right/bottom covers "left:-9999px" tricks.
_MARK_HIDDEN_JS = """attr => {
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const hidden = style.display === 'none' || style.visibility === 'hidden'
      || style.opacity === '0' || rect.width === 0 || rect.height === 0
      || rect.right < 0 || rect.bottom < 0 || el.closest('[aria-hidden="true"]') !== null;
    if (hidden) el.setAttribute(attr, '1'); else el.removeAttribute(attr);
  }
}"""


@dataclass(frozen=True)
class FrameDocument:
    """The HTML of the page or one of its iframes (embedded ATS forms live in iframes)."""

    name: str  # "page" or "frame_<n>"
    url: str
    html: str
    # The live Playwright frame, to fill a form found in this document.
    # None for saved pages (tests, offline inspection).
    frame: object = field(default=None, compare=False, repr=False)


async def follow_company_site_button(context: BrowserContext, page: Page) -> Page:
    """Click "Apply on company site" once and return the page it leads to.

    Naukri opens the company site in a new tab; if no tab opens, the click
    navigated the same tab. Only call this for an approved job (or from the
    inspector): it is a real click on Naukri.
    """
    button = page.locator(COMPANY_SITE_BUTTON).first
    try:
        async with context.expect_page(timeout=NEW_TAB_TIMEOUT_MS) as new_tab:
            await button.click()
        target = await new_tab.value
    except PlaywrightTimeoutError:
        target = page
    try:
        await target.wait_for_load_state("load")
    except PlaywrightTimeoutError:
        # Slow third-party scripts; what has rendered may still be readable.
        logger.warning("company_site_load_timeout", url=target.url)
    await target.wait_for_timeout(SETTLE_MS)
    logger.info("company_site_opened", url=target.url)
    return target


async def read_documents(page: Page) -> list[FrameDocument]:
    """HTML of the page plus every non-blank iframe, hidden fields marked.

    A frame that cannot be read is skipped.
    """
    await page.main_frame.evaluate(_MARK_HIDDEN_JS, HIDDEN_FIELD_ATTR)
    documents = [FrameDocument("page", page.url, await page.content(), page.main_frame)]
    for number, frame in enumerate(page.frames):
        if frame == page.main_frame or frame.url in ("", "about:blank"):
            continue
        try:
            await frame.evaluate(_MARK_HIDDEN_JS, HIDDEN_FIELD_ATTR)
            html = await frame.content()
        except PlaywrightError:
            # Detached while loading (ads, trackers); not the form.
            continue
        documents.append(FrameDocument(f"frame_{number}", frame.url, html, frame))
    return documents


async def open_job_form(page: Page, selector: str) -> None:
    """Click the in-page link that opens the job's hidden form (see find_job_opener).

    One click, no typing. The selector only matches links that stay on the page.
    """
    await page.locator(selector).first.click()
    await page.wait_for_timeout(OPEN_FORM_WAIT_MS)
    logger.info("company_site_form_opened", selector=selector)


async def open_company_page(page: Page, url: str) -> None:
    """Load a company page in this tab: a known company URL, or this job's own
    apply page (see find_job_page_link).

    An ordinary page load: nothing is typed, clicked or sent. Slow third-party
    scripts may keep "load" from firing in time (zaax.com, 2026-10-15: the
    HTML alone took 7 s); what has rendered is still read, as after a click.
    """
    try:
        await page.goto(url, wait_until="load")
    except PlaywrightTimeoutError:
        logger.warning("company_page_load_timeout", url=url)
    await page.wait_for_timeout(SETTLE_MS)
    logger.info("company_page_opened", url=page.url)


async def screenshot_form(page, path: Path) -> bool:
    """Screenshot just the application form (a visible <form> with a file input).

    page may be a Page or a Frame (a form inside an ATS iframe).

    A full-page screenshot misses a form inside a scrollable modal (kmgus.com,
    2026-10-15): the modal shows its top part only. An element screenshot
    scrolls the form into view first. Returns False if there is no such form.
    """
    forms = page.locator("form").filter(has=page.locator("input[type='file']"))
    for index in range(await forms.count()):
        form = forms.nth(index)
        if await form.is_visible():
            await form.screenshot(path=path)
            return True
    return False


@dataclass(frozen=True)
class FillResult:
    label: str
    value: str
    # "filled" (and read back the same), or what went wrong.
    status: str


def _attr_selector(attr: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attr}="{escaped}"]'


async def _fill_one(form, field, value: str) -> str:
    """Put one value into one field and read it back. Returns the status."""
    if field.kind == "radio":
        group = form.locator(f"input[type='radio']{_attr_selector('name', field.name)}")
        option = form.get_by_role("radio", name=value, exact=True).and_(group)
        await option.check()
        return "filled" if await option.is_checked() else "not checked after click"

    selector = _attr_selector("id", field.id) if field.id else _attr_selector("name", field.name)
    element = form.locator(selector)
    if await element.count() != 1:
        return f"not found (or not unique): {selector}"

    if field.kind == "file":
        await element.set_input_files(value)
        got = await element.evaluate("e => e.files.length ? e.files[0].name : ''")
        expected = Path(value).name
    elif field.kind == "select":
        await element.select_option(label=value)
        got = await element.evaluate("e => e.options[e.selectedIndex].text.trim()")
        expected = value
    else:
        await element.fill(value)
        got = await element.input_value()
        expected = value
    return "filled" if got == expected else f"read back {got!r}, expected {expected!r}"


async def fill_form(page, form_index: int, mapped) -> list[FillResult]:
    """Fill every field that has an answer, inside the form_index-th <form>
    of page (a Page, or the Frame of an ATS iframe).

    Never clicks a submit button: only fill / select / check / attach.
    A field that fails is reported and the rest are still filled, so the
    screenshot shows everything that worked.
    """
    form = page.locator("form").nth(form_index)
    results = []
    for item in mapped:
        if item.answer is None:
            continue
        try:
            status = await _fill_one(form, item.field, item.answer.value)
        except PlaywrightError as error:
            status = "error: " + str(error).splitlines()[0]
        results.append(FillResult(item.field.label, item.answer.value, status))
    return results


# The current values of the form_index-th <form>, as I see them in the
# browser. Passwords, files, hidden inputs and checkboxes are left out, so no
# secret ever leaves the page. A select reports its option text ("" for a
# placeholder option with an empty value); a radio only when checked, with
# its label text (the option text company_portal parses).
_FORM_VALUES_JS = """formIndex => {
  const form = document.querySelectorAll('form')[formIndex];
  if (!form) return null;
  const skip = ['password', 'file', 'hidden', 'submit', 'button', 'image', 'reset', 'checkbox'];
  const values = [];
  for (const el of form.querySelectorAll('input, select, textarea')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (skip.includes(type)) continue;
    let value = el.value;
    if (el.tagName === 'SELECT') {
      const option = el.options[el.selectedIndex];
      value = option && option.value !== '' ? option.text : '';
    } else if (type === 'radio') {
      if (!el.checked) continue;
      const label = el.labels && el.labels.length ? el.labels[0].innerText : '';
      value = label || el.getAttribute('aria-label') || el.placeholder || el.value;
    }
    values.push({name: el.name || '', id: el.id || '', type: type, value: (value || '').trim()});
  }
  return values;
}"""

# Name of the page -> Python callback; only our own copy of the page sees it.
_VALUES_BINDING = "__jobAgentFormValues"

# Report the values on every change, on submit and on any button click in the
# form: clicking Submit may navigate away before the form can be read again.
_WATCH_FORM_JS = (
    "formIndex => {\n  const read = " + _FORM_VALUES_JS + ";\n"
    "  const form = document.querySelectorAll('form')[formIndex];\n"
    "  if (!form) return false;\n"
    f"  const report = () => window.{_VALUES_BINDING}(read(formIndex));\n"
    "  form.addEventListener('change', report, true);\n"
    "  form.addEventListener('submit', report, true);\n"
    "  form.addEventListener('click', e => {\n"
    "    if (e.target.closest('button, input[type=submit]')) report();\n"
    "  }, true);\n"
    "  return true;\n}"
)


class FormWatch:
    """The latest form values the page reported while I filled it in."""

    def __init__(self) -> None:
        self.latest: list[dict] | None = None

    def _report(self, _source, values) -> None:
        if values is not None:
            self.latest = values


async def read_form_values(page, form_index: int) -> list[dict] | None:
    """Values of the form_index-th <form> now; None if the form is gone.

    page may be a Page or a Frame. Only reads, never changes a field.
    """
    try:
        return await page.evaluate(_FORM_VALUES_JS, form_index)
    except PlaywrightError:
        return None  # navigated away or closed


async def watch_form(page, form_index: int) -> FormWatch:
    """Keep the values I type into the form, also after Submit leaves the page.

    page may be a Page or a Frame (the binding lives on the Page). Call once
    per page. Only listens; never clicks or types.
    """
    watch = FormWatch()
    owner = getattr(page, "page", page)  # a Frame knows its Page
    await owner.expose_binding(_VALUES_BINDING, watch._report)
    if not await page.evaluate(_WATCH_FORM_JS, form_index):
        logger.warning("form_watch_no_form", form_index=form_index)
    return watch
