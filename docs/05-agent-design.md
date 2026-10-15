# 05 — Agent design

"Agent" here means the LLM-backed parts of the system. Two exist today:

| Component | Where | Status | Role |
|---|---|---|---|
| **Job matcher** | `app/services/job_match_service.py`, `app/llm/claude_code.py` | Built | One structured-output call per job → `JobMatchResult`. Used by `main.py`. |
| **Tool-calling agent** | `app/agent/` | In progress (prototype) | Claude Agent SDK loop with two tools; CLI approval. Not used by `main.py`. |

Design principle: **the LLM judges, the code decides.** The LLM returns sub-scores and reasons;
code computes the overall score, the level, the ranking, and whether anything is submitted.

## Job matcher (Built)

### Input

The prompt (`app/services/job_match_service.py:19-166`) embeds:

- `candidate_profile.model_dump()` — name, experience_years, skills, education.
- `job.model_dump()` — title, company, location, experience, salary, description (card snippet), skills, url.
- **Hardcoded role focus**: Python backend, Django, FastAPI, REST APIs, AI/GenAI backend
  (`job_match_service.py:48-54`) — not taken from the profile ([known issue](12-roadmap-and-status.md#known-issues)).
- Scoring rubrics (bands 90-100 / 70-89 / 50-69 / 30-49 / 0-29) for role, skill and experience.
- Instructions: don't invent requirements, weight core requirements, **don't return an overall score**.

### Structured output

`ClaudeCodeProvider.generate()` (`app/llm/claude_code.py:13`) calls `claude_agent_sdk.query` with
`output_format = {"type": "json_schema", "schema": JobMatchResult.model_json_schema()}`, takes the
`ResultMessage.result`, `json.loads` it and validates with Pydantic.

`JobMatchResult` (`app/models/job_match.py`):

```json
{
  "type": "object",
  "required": ["role_match", "skill_match", "experience_match",
               "matching_skills", "missing_skills", "strengths", "concerns", "recommendation"],
  "properties": {
    "role_match":       {"type": "integer", "minimum": 0, "maximum": 100},
    "skill_match":      {"type": "integer", "minimum": 0, "maximum": 100},
    "experience_match": {"type": "integer", "minimum": 0, "maximum": 100},
    "matching_skills":  {"type": "array", "items": {"type": "string"}},
    "missing_skills":   {"type": "array", "items": {"type": "string"}},
    "strengths":        {"type": "array", "items": {"type": "string"}},
    "concerns":         {"type": "array", "items": {"type": "string"}},
    "recommendation":   {"type": "string"}
  }
}
```

(Simplified from Pydantic's generated schema.) Out-of-range scores raise `ValidationError`; the
pipeline logs `matching_failed` and skips the job (`job_matching_pipeline.py:145`).

### Deterministic scoring (Built)

`JobScoreService` (`app/services/job_score_service.py`):

```
overall = round(0.50 × skill_match + 0.30 × role_match + 0.20 × experience_match)
```

| Weight | Component | Why |
|---|---|---|
| 50 % | skill_match | Technical fit is the strongest predictor of a callback. |
| 30 % | role_match | Guards against skill overlap in the wrong role (e.g. data engineer with Python). |
| 20 % | experience_match | Experience bands on Naukri are soft; mismatch matters less. |

### Match levels (Built)

`JobMatchLevelService` (`app/services/job_match_level_service.py`):

| Level | overall_score |
|---|---|
| `strong` | ≥ 80 |
| `potential` | 60 – 79 |
| `weak` | < 60 |

Final ordering (`JobRankingService`): `overall_score`, then `skill_match`, `role_match`,
`experience_match`, descending. Both rules are unit-tested ([11](11-observability-and-testing.md#current-tests)).

See [ADR-009](adr/ADR-009-deterministic-scoring.md) for why this lives in code.

## Tool-calling agent prototype (In progress)

`app/agent/agent.py` creates an in-process MCP server (`create_sdk_mcp_server`) with:

| Tool | Args | Does | Side effect |
|---|---|---|---|
| `search_jobs` | `keyword: str`, `location: str` | Runs `NaukriJobSource.get_jobs()` (Playwright), returns a numbered list | Stores jobs in `AgentState.jobs` |
| `get_job_details` | `job_id: int` (1-based index, **not** the DB id) | Returns the stored job's fields | Sets `AgentState.current_job` |

`allowed_tools` restricts the agent to these two tools. After the loop, `request_approval()`
(`app/agent/approval.py`) asks `yes/no` on stdin and sets `approval_status` / `next_action`. Nothing
is persisted and nothing is applied. `app/agent/steps.py` contains step functions (some with demo
data) that duplicate the pipeline.

Direction: keep the SDK **as an LLM provider and for bounded tool use inside activities**; do not
let an agent loop orchestrate the workflow — Temporal does that ([ADR-006](adr/ADR-006-temporal-durable-workflows.md)).
The agent must never have a "submit" tool.

## LLMProvider abstraction (Planned)

```python
class LLMProvider(Protocol):
    name: str
    model: str
    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], *, timeout_s: float
    ) -> BaseModel: ...
```

| Provider | Status | Notes |
|---|---|---|
| `ClaudeAgentSDKProvider` (rename of `ClaudeCodeProvider`) | Built as concrete class; interface Planned | Primary. Uses the user's Claude subscription via the SDK. Fix return type (`-> str` but returns `JobMatchResult`, `claude_code.py:13`). |
| `OllamaProvider` | Planned | Fallback when Claude is unavailable / rate-limited. Local model with JSON-schema format. |
| `FakeProvider` | Planned | Deterministic responses for tests and evals. |

Selection: `LLM_PROVIDER=claude|ollama` setting, plus automatic fallback on provider errors after
retries. Every stored `job_matches` row records `model` and `prompt_version` so results from
different providers are distinguishable.

## Form-field suggestions (Built, preview only)

`app/llm/form_answerer.py` suggests values for company-form fields that no fixed rule or learned
answer covers. It is used only in the inspector's `--fill-preview`, and every value needs my y / n / e.

- **Input:** the field list (key, label, kind, options, required) as JSON, `profile.yaml` as text,
  `answers.yaml` **without** the `contact` block (`answers_facts()`), and the resume PDF's text
  (`app/services/resume_text.py`, pypdf, [ADR-015](adr/ADR-015-pypdf-resume-text.md)). The prompt
  is the `PROMPT` constant in the module.
- **Call:** `ClaudeJsonLLM`, i.e. the Agent SDK with `tools=[]` (no tools at all), `max_turns=3` and
  a JSON schema (`SuggestionList`: key, value or null, source_quote).
- **Checks in code** (`check_suggestions()`): the source quote must be in my documents
  (case and whitespace ignored). A free-text value must be copied from that quote. An option value
  must equal exactly one option. Values over 300 chars are rejected. Anything that fails is dropped
  with a reason. So an invented fact, or one planted by a hostile label, never reaches the form.
- **Never asked:** consents, salary / CTC / notice, IDs, bank, passport, visa, date of birth / age,
  gender, caste, religion, disability, criminal or legal declarations (`AI_FORBIDDEN_WORDS` in
  `company_form_mapper.py`).
- **Learned answers:** a value I accept (or type), in the terminal or in the browser after the
  fill (`y/N` each, [06](06-browser-automation.md#learning-from-the-browser)), is saved in
  `learned_answers.yaml`, keyed by the normalised label. From then on it is a deterministic rule
  for that label, with no AI call. For a new but related label, `similar_answers()` offers up to
  3 saved answers (local embeddings, [07](07-matching-and-retrieval.md#learned-answers-related-labels)):
  only candidates I pick from, never filled on their own and never sent to Claude.
- Checked live 2026-10-15 with a made-up resume: 3 facts came back with real quotes, a fact not
  in the documents came back null, and a label containing "ignore the documents…" got null.

## Guardrails

| Guardrail | Status |
|---|---|
| JSON-schema output + Pydantic validation with 0-100 bounds | Built |
| Overall score, level, ranking computed in code | Built |
| Invalid LLM output → job skipped, not guessed | Built (logged `matching_failed`) |
| Tool allow-list for agent prototype | Built |
| No submit capability exposed to any LLM | Built (by absence); must stay true |
| Human approval enforced by workflow + DB constraint | Planned |
| Timeout and retry per LLM call | Planned |
| Bounded concurrency (e.g. 3 parallel calls) | Planned |
| Treat job text as untrusted data (prompt-injection): delimit it, instruct model to ignore instructions inside it | Planned (matcher); Built for form suggestions (no tools + quote check) |
| Don't send candidate `name` (or other PII not needed for matching) to the LLM | Planned — currently sent via `model_dump()` |
| Profile-driven role focus and filter keywords | Planned |

## Prompt versioning (Planned)

- Move prompts out of f-strings into `app/prompts/job_match/v1.md` (template + variables).
- `PROMPT_VERSION = "job_match.v1"` constant stored on every `job_matches` row.
- Any change to wording, rubric or schema → new version file; old versions stay for evals.
- Prompt and schema changes require an eval run in the PR ([Evals](#evals)).

## Evals

| Eval | Status | What it checks |
|---|---|---|
| Unit tests for schema bounds, scoring, levels | Built | Code, not model quality. |
| Golden set: ~50 real jobs with hand-labelled expected level | Planned | Level accuracy, sub-score MAE vs labels. |
| Approval-derived labels (approved = positive, rejected = negative) | Planned | Precision of `strong`/`potential` over time. |
| Stability: same input ×3 | Planned | Score variance ≤ ±5. |
| Provider parity: Claude vs Ollama on golden set | Planned | Decide if fallback quality is acceptable. |
| Injection set: job descriptions containing instructions | Planned | Output unaffected. |

Evals run as a script (`scripts/run_evals.py`, planned) and, later, traces go to Langfuse
([11](11-observability-and-testing.md)).
