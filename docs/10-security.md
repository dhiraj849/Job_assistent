# 10 — Security

Threat model in one line: a single user's machine holds their resume data, a logged-in Naukri
session, and LLM access. The main risks are **leaking secrets or PII** (via git, logs, LLM prompts)
and **the system acting on the user's behalf without consent**.

## Open incident: secrets committed to git

| Item | Detail |
|---|---|
| Where | `server.py:21-26` — comment lines containing token-like strings (one has the shape of an X/Twitter API bearer token; others look like client IDs / secrets). |
| Since | Initial commit `39612aa`. |
| Exposure | That commit is on `origin/main` (GitHub). **Treat every value as compromised.** |
| Related | `app/config.py:48-51` defines `X_CLIENT_ID` / `X_CLIENT_SECRET` "used by the MCP server experiment". |

Required actions, in order:

1. **Rotate / revoke** every credential in those lines at the issuing provider (X developer portal,
   and any other service they belong to). Rotation is the fix; deleting lines is not.
2. Delete the comment lines from `server.py` (and move or remove the MCP experiment —
   [open question](12-roadmap-and-status.md#open-questions)).
3. Optional, only after rotation: rewrite history (`git filter-repo`) and force-push. This reduces
   future exposure but cannot undo past exposure (forks, caches, clones).
4. Add secret scanning: `gitleaks` as a pre-commit hook and in CI; enable GitHub secret scanning /
   push protection on the repo.

Do not copy the values into issues, PRs, chats or docs while doing this.

## Secrets handling

| Rule | Status |
|---|---|
| Secrets only in `.env` (gitignored) or the process environment | Built (`.gitignore` has `.env`) |
| `.env.example` lists variable **names** with dummy values only | Built (incomplete: missing `POSTGRES_*`) |
| Secret settings typed as `SecretStr` so they don't print in reprs/logs | Built for `POSTGRES_PASSWORD`, `X_CLIENT_SECRET` |
| No secrets in code, comments, notebooks or test fixtures | **Violated** — see incident above |
| `alembic/env.py` renders the DB URL with the password (`hide_password=False`) into Alembic config; never log or print that config | Built as-is; keep in mind |
| No Anthropic API key in the repo; Claude access is via the logged-in Claude Code session | Built |
| Pre-commit `gitleaks` + CI secret scan | Planned |
| Postgres/Qdrant bound to `127.0.0.1` only (currently published on all interfaces: `5433`, `6333`, `6334`) | Planned |
| Qdrant API key if ever exposed beyond localhost | Planned |

## Browser session

Applying needs a logged-in Naukri session ([06](06-browser-automation.md#session-reuse-via-storage_state-built),
[ADR-014](adr/ADR-014-encrypted-naukri-session.md)). Built:

- The system never stores the Naukri **password**. The user logs in manually in a headed browser
  (`scripts/naukri_login.py`).
- The saved `storage_state` (cookies + localStorage) grants full account access. It is stored:
  - at `secrets/naukri_state.enc` (`secrets/` is gitignored), folder mode `700`, file mode `600`;
  - **encrypted at rest** with Fernet using `NAUKRI_STATE_KEY` (`SecretStr`, from `.env`);
    decrypted into memory only when creating the browser context;
  - never logged: `session_store` logs only cookie count, domains and origin count.
- Never uploaded anywhere or sent to the LLM (Planned rule for MinIO / LLM code).
- On session expiry, re-run the login script; no automatic refresh.
- Losing `NAUKRI_STATE_KEY` only means logging in again; rotating it = new key + new login.

Inspection artifacts (`artifacts/inspect/<job_id>/`, HTML + screenshots of logged-in pages) contain
PII and are gitignored. `answers.yaml` (application answers: CTC, notice period…) is gitignored;
only `answers.example.yaml` is committed.

## PII in the candidate profile and resume

| Data | Where | Rule |
|---|---|---|
| `profile.yaml` (name, experience, education, skills) | Local file, gitignored | Built. Never commit; `profile.example.yaml` holds dummy data only. |
| Resume file | MinIO (planned) | Private bucket, no public URLs; local only. |
| Profile sent to Claude | Prompt in `job_match_service.py` | **Currently the full `model_dump()` including `name` is sent.** Planned: send only fields needed for matching (experience, skills, education, target roles). |
| Filled application forms / screenshots | MinIO (planned) | Contain PII; same retention as resume; deletable per job. |
| Job postings | Postgres | Public data; low sensitivity. |

The Anthropic data-handling terms of the user's Claude plan apply to anything sent in prompts.
Ollama fallback keeps data fully local.

## Consent and action safety

- No code path may submit an application without a recorded approval (workflow + DB CHECK
  constraint, [04](04-data-model.md#planned-indexes-and-constraints)).
- No LLM-callable tool may submit, log in, or change account settings.
- `APPLY_DRY_RUN=true` by default ([06](06-browser-automation.md#dry-run-mode-planned)).
- Treat scraped job text as untrusted input to the LLM (prompt injection) ([05](05-agent-design.md#guardrails)).

## What must never be logged

| Never log | Why | Current state |
|---|---|---|
| Passwords, tokens, API keys, `SecretStr` values, full DB URLs | Credential leak | OK |
| `storage_state` contents, cookies, auth headers | Account takeover | OK (`session_store` logs counts/domains only; tested) |
| Candidate name, email, phone, address | PII | **Violated**: `profile_loaded` logs `name=candidate.name` (`main.py:23`, `app/agent/agent.py:29-33`) |
| Full prompts or full LLM responses at INFO or above | Contain profile PII | OK in `main.py`; `app/agent/agent.py:80` logs every SDK message at DEBUG — keep DEBUG off in shared logs |
| Resume text, form field values | PII | n/a yet |

Allowed: job IDs, job titles/companies (public), counts, durations, scores, error types, workflow IDs.
When Langfuse is added, prompts will be stored there — self-hosted only, and with the profile
minimised as above.

## Dependency hygiene

- Lockfile (`uv.lock`) committed — Built. Undeclared dependencies break this ([12](12-roadmap-and-status.md#known-issues)).
- Pin container images (Postgres `16`, Qdrant `v1.18.2`) — Built; move Postgres to a minor tag later.
- Planned CI: `pip-audit` (or `uv` equivalent) and Dependabot/Renovate.
