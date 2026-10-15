"""Decide what an approved company-site job needs, from the company page's HTML.

Pure, no browser (the applier fetches the documents). The worker never
fills a company form: it cannot wait for me to solve a CAPTCHA or an OTP.
It only says whether the form can be filled by the fill session
(READY_FOR_YOU) or needs me from the start (NEEDS_MANUAL).
"""

from app.browser.company_portal import (
    PageReport,
    PortalType,
    application_form,
    inspect_page,
    split_stops,
)
from app.browser.company_site_page import FrameDocument
from app.models.apply_result import ApplierResult, ApplyOutcome, CompanySite

FILL_COMMAND = "uv run python -m scripts.apply_company_site {job_id}"


def _portal(reports: list[PageReport]) -> PortalType:
    """The most specific portal seen on the page or in any frame."""
    known = [r.portal for r in reports if r.portal not in (PortalType.UNKNOWN, PortalType.GENERIC_FORM)]
    if known:
        return known[0]
    return reports[0].portal


def company_site_result(job_id: int, documents: list[FrameDocument]) -> ApplierResult:
    reports = [inspect_page(doc.url, doc.html) for doc in documents]
    portal = _portal(reports)

    # The page itself first, then ATS iframes: the fill session opens that URL directly.
    with_form = next((r for r in reports if application_form(r.fields)), None)
    if with_form is None:
        site = CompanySite(url=reports[0].url, portal=portal.value)
        stops = "; ".join(reports[0].hard_stops) or "no application form we can fill"
        return ApplierResult(
            outcome=ApplyOutcome.NEEDS_MANUAL,
            reason=f"company site ({portal.value}): {stops}. Apply at {site.url}",
            company_site=site,
        )

    steps, blocking = split_stops(with_form.hard_stops)
    # The page's own URL, not the iframe's: ATS embed URLs carry tokens that
    # expire. The fill session finds the form's frame again on that page.
    site = CompanySite(url=reports[0].url, portal=with_form.portal.value, human_steps=steps)
    if blocking:
        return ApplierResult(
            outcome=ApplyOutcome.NEEDS_MANUAL,
            reason=f"company site ({site.portal}): {'; '.join(blocking)}. Apply at {site.url}",
            company_site=site,
        )

    you = f"; you will do: {', '.join(steps)}" if steps else ""
    return ApplierResult(
        outcome=ApplyOutcome.READY_FOR_YOU,
        reason=f"company site form ready ({site.portal}{you}). Run: {FILL_COMMAND.format(job_id=job_id)}",
        company_site=site,
    )
