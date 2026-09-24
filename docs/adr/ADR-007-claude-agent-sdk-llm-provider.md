# ADR-007 — Use the Claude Agent SDK behind an `LLMProvider` interface, with Ollama as fallback

- **Status:** Accepted
- **Implementation:** In progress — Claude via SDK Built (`app/llm/claude_code.py`); interface and Ollama Planned
- **Date:** 2026-09-24
- **Supersedes:** the earlier Ollama-first plan

## Context

Job evaluation needs a capable model returning strict JSON. The only paid resource allowed is the
user's existing Claude subscription. The Claude Agent SDK can use that subscription (through Claude
Code) and supports JSON-schema output. Local models via Ollama are free but weaker and need local compute.

## Decision

- **Primary:** Claude through `claude-agent-sdk`, `output_format = json_schema` from the Pydantic model.
- **Interface:** services depend on `LLMProvider.generate_structured(prompt, schema, timeout_s)`,
  never on an SDK directly ([05](../05-agent-design.md#llmprovider-abstraction-planned)).
- **Fallback:** `OllamaProvider` when Claude fails after retries or is rate-limited; selectable by config.
- Every stored result records `model` and `prompt_version`.
- `claude-agent-sdk` must be a declared dependency ([known issue #2](../12-roadmap-and-status.md#known-issues)).

## Alternatives considered

| Option | Why not |
|---|---|
| Ollama-first (original plan) | Lower quality on nuanced matching; Claude subscription is already paid for. |
| Anthropic Messages API | Per-token billing on top of the subscription — violates the cost constraint. |
| OpenAI / other hosted APIs | Paid. |
| LangChain as abstraction | Heavy for a single structured-output call; a small Protocol is enough. |

## Consequences

- Positive: strong model at no extra cost; swappable providers; testable with a `FakeProvider`.
- Negative: subscription usage limits cap throughput; SDK depends on a local Claude Code login.
- Negative: two providers means evals must check both.
- Follow-ups: fix `ClaudeCodeProvider.generate` return type; timeouts/retries; declare dependency.
