"""Read a saved Naukri job detail page (HTML string) into a JobDetailPage.

Pure function, no browser: the activity fetches the HTML, this file decides
what it means, and tests run it on saved pages (tests/fixtures/naukri/).

Order: JobPosting JSON-LD (all fields) -> rendered JD block (text only) ->
DetailParseError. Never returns an empty or near-empty description: callers
keep the search-card snippet instead of saving a broken JD.
"""

import json
from datetime import date
from html.parser import HTMLParser

from app.browser.naukri_selectors import JOB_DESCRIPTION_CLASS_PREFIX, JOB_POSTING_TYPE
from app.models.job_details import JobDetailPage, JobDetails

# Shorter than this is a broken page, not a real JD (the card snippet is ~90).
MIN_DESCRIPTION_CHARS = 50

# Tags that end a line when turning HTML into text.
_BLOCK_TAGS = {"p", "br", "div", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}
# Tags without a closing tag; they must not change the nesting depth.
_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed"}


class DetailParseError(Exception):
    """The page has no usable JD (selectors broken, or not a job page)."""


def parse_job_detail(html: str) -> JobDetailPage:
    posting = _find_job_posting(html)
    if posting is not None:
        description = html_to_text(str(posting.get("description") or ""))
        if len(description) >= MIN_DESCRIPTION_CHARS:
            return JobDetailPage(description=description, details=_details_from(posting))

    # JSON-LD missing or empty: fall back to the rendered JD block.
    description = _description_from_dom(html)
    if len(description) >= MIN_DESCRIPTION_CHARS:
        return JobDetailPage(description=description, details=JobDetails(source="dom"))

    raise DetailParseError(
        f"no job description found (JSON-LD {JOB_POSTING_TYPE} and "
        f"'{JOB_DESCRIPTION_CLASS_PREFIX}' both missing or under {MIN_DESCRIPTION_CHARS} chars)"
    )


def html_to_text(html: str) -> str:
    """HTML fragment -> plain text with one line per block, entities decoded."""
    collector = _TextCollector(root_class_prefix=None)
    collector.feed(html)
    collector.close()
    return collector.text()


# --- JSON-LD -------------------------------------------------------------------


class _JsonLdScripts(HTMLParser):
    """Collect the bodies of <script type="application/ld+json"> tags."""

    def __init__(self):
        super().__init__()
        self.scripts: list[str] = []
        self._inside = False

    def handle_starttag(self, tag, attrs):
        self._inside = tag == "script" and dict(attrs).get("type") == "application/ld+json"
        if self._inside:
            self.scripts.append("")

    def handle_data(self, data):
        if self._inside:
            self.scripts[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self._inside = False


def _find_job_posting(html: str) -> dict | None:
    parser = _JsonLdScripts()
    parser.feed(html)
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue  # one broken block must not hide a good one
        # A block may hold one object or a list of them.
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == JOB_POSTING_TYPE:
                return item
    return None


def _details_from(posting: dict) -> JobDetails:
    salary = _text(_get(posting, "baseSalary", "value", "value"))
    if salary and salary.lower() == "not disclosed":
        salary = None

    return JobDetails(
        source="json_ld",
        skills=[s.strip() for s in posting.get("skills") or [] if isinstance(s, str) and s.strip()],
        salary=salary,
        experience_months=_int(_get(posting, "experienceRequirements", "monthsOfExperience")),
        employment_type=_text(posting.get("employmentType")),
        industry=_text(posting.get("industry")),
        # Naukri puts the department in occupationalCategory and the role
        # (shown as "Role:" on the page) in responsibilities.
        department=_text(posting.get("occupationalCategory")),
        role=_text(posting.get("responsibilities")),
        education=_text(_get(posting, "qualifications", "educationalLevel")),
        date_posted=_date(posting.get("datePosted")),
        valid_through=_date(posting.get("validThrough")),
    )


def _get(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _text(value) -> str | None:
    # Naukri writes "-" for "not given".
    if not isinstance(value, str) or value.strip() in ("", "-"):
        return None
    return value.strip()


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


# --- Rendered DOM fallback -----------------------------------------------------


class _TextCollector(HTMLParser):
    """Collect text, either of the whole input or only inside the first
    element whose class starts with root_class_prefix."""

    def __init__(self, root_class_prefix: str | None):
        super().__init__()  # convert_charrefs=True decodes &amp; etc.
        self._prefix = root_class_prefix
        # Depth inside the root element; None = not inside (yet).
        self._depth: int | None = 0 if root_class_prefix is None else None
        self._done = False
        self._parts: list[str] = []
        self._skip = 0  # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if self._done:
            return
        if self._depth is None:
            classes = (dict(attrs).get("class") or "").split()
            if any(c.startswith(self._prefix) for c in classes) and tag not in _VOID_TAGS:
                self._depth = 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "li":
            self._parts.append("- ")
        if tag not in _VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if self._done or self._depth is None or tag in _VOID_TAGS:
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        self._depth -= 1
        if self._prefix is not None and self._depth == 0:
            self._done = True  # closed the root element

    def handle_data(self, data):
        if self._depth is not None and not self._done and not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self._parts).splitlines()]
        # Drop empty lines and list bullets left without text.
        return "\n".join(line for line in lines if line and line != "-")


def _description_from_dom(html: str) -> str:
    collector = _TextCollector(root_class_prefix=JOB_DESCRIPTION_CLASS_PREFIX)
    collector.feed(html)
    collector.close()
    return collector.text()
