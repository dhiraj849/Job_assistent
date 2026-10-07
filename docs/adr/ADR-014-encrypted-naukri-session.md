# ADR-014 — Store the Naukri login session encrypted with Fernet

- **Status:** Accepted
- **Implementation:** Built
- **Date:** 2026-09-24
- **Deciders:** dhiraj

## Context

Applying needs a logged-in Naukri account. Logging in involves OTPs and bot checks, so it must be
done by a human. Playwright can save the logged-in browser state (`storage_state`: cookies +
localStorage) and reuse it, but that data grants full access to the account, like a password.
Constraints: free, self-hosted, single user on one machine, no password stored anywhere.

## Decision

The user logs in manually once (`scripts/naukri_login.py`, headed browser). The resulting
`storage_state` is encrypted with **Fernet** (`cryptography` package) using `NAUKRI_STATE_KEY` from
`.env`, and written to `secrets/naukri_state.enc` (gitignored, folder `0700`, file `0600`).
`app/browser/session_store.py` is the only code that encrypts or decrypts it; it decrypts into memory
only when creating a browser context and never logs cookie names or values.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Plain JSON file, gitignored | Simplest | A copied file or backup leaks the account | Too risky for a session cookie |
| `age` / GPG | Strong, standard file encryption | Extra binary or subprocess, key management outside Python | More moving parts for one file |
| OS keyring | Uses the OS secret store | State can exceed keyring size limits; differs per OS / headless servers | Not portable to a home server |
| Store Naukri password and log in automatically | Fully unattended | Stores a password; OTP / captcha still break it | Violates "never store the password" |

## Consequences

- **Positive:** A leaked file alone is useless without the key; secrets stay out of git and logs;
  the key is a normal `SecretStr` setting.
- **Negative / costs:** The key lives in `.env` on the same machine, so this protects against file
  leaks (backups, copies, commits), not against a compromised machine. Sessions expire and need a
  manual re-login.
- **Follow-ups:** verify `LOGGED_IN_MARKER` on a live page; add `NAUKRI_STATE_KEY` to `.env.example`;
  raise a non-retryable `SessionExpired` error when apply runs inside Temporal.
