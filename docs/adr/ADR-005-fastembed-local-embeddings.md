# ADR-005 — Generate embeddings locally with fastembed (bge-small-en-v1.5)

- **Status:** Accepted
- **Implementation:** Built (`app/vector/embedder.py`)
- **Date:** 2026-09-24

## Context

Semantic ranking needs text embeddings for every job and the profile. The project must stay free
and self-hosted, and should run on a laptop CPU.

## Decision

- Use **fastembed** with `BAAI/bge-small-en-v1.5` (384 dimensions, ONNX runtime, CPU).
- The model name is a constant, mirrored in the Qdrant collection name (see ADR-004).
- Embedding texts are defined in one place (`app/vector/texts.py`).

## Alternatives considered

| Option | Why not |
|---|---|
| sentence-transformers | Pulls in PyTorch (large install), slower on CPU for this use. |
| Ollama embeddings (e.g. nomic-embed-text) | Requires Ollama running for every discovery; viable later. |
| Hosted APIs (OpenAI, Voyage, Cohere) | Paid; sends data to a third party. |
| Larger bge-base / bge-large | Better quality, slower; not justified until evals show a need. |

## Consequences

- Positive: free, offline, small download, fast enough for hundreds of jobs.
- Negative: English-focused, 512-token limit (job text is truncated to 1500 chars); first run downloads the model.
- Negative: fastembed is synchronous — must run in a thread from async code.
- Follow-ups: evaluate bge-base on the golden set before switching (new collection per ADR-004).
