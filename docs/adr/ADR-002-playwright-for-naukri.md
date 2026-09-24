# ADR-002 — Use Playwright browser automation for Naukri

- **Status:** Accepted
- **Implementation:** Built for search + card extraction; detail page and apply Planned
- **Date:** 2026-09-24

## Context

Naukri offers no public API for job seekers. Search results and job pages are rendered client-side;
applying requires a logged-in session and form interaction. Automation may conflict with Naukri's
Terms of Service ([01](../01-product-overview.md#ethics-and-naukri-terms-of-service-risk)).

## Decision

- Use the **Python Playwright library (async API) with Chromium**, running on the user's machine.
- **Headed by default** (`BROWSER_HEADLESS=false`); headless is configurable.
- No stealth plugins, CAPTCHA solving or proxy rotation. A challenge page stops the run.
- Reuse login via `storage_state` (planned); the password is never stored.
- Selectors are centralised and covered by HTML-fixture tests (planned).

## Alternatives considered

| Option | Why not |
|---|---|
| `requests`/`httpx` + BeautifulSoup | Content is JS-rendered; login and apply need a real browser. |
| Reverse-engineered internal JSON APIs | Undocumented, brittle, higher ToS risk, and apply flow still needs browser state. |
| Selenium | Older API, no auto-waiting, weaker tooling (tracing, codegen). |
| Third-party scraping services | Paid, and send the user's session to a third party. |

## Consequences

- Positive: real browser behaviour; user can watch every step; `storage_state` makes sessions portable.
- Negative: selectors break when Naukri changes markup; headed mode needs a display; slow compared with HTTP.
- Negative: ToS / account-ban risk is accepted and mitigated by volume limits and human approval.
- Follow-ups: detail-page scraping, rate limits, screenshots, dry-run ([06](../06-browser-automation.md)).
