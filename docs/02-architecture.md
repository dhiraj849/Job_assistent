# 02 — Architecture

C4-style views drawn as Mermaid flowcharts. Solid green = **Built**, yellow = **In progress**,
dashed grey = **Planned**.

## 1. System context

```mermaid
flowchart LR
    user(["Candidate<br/>(single user)"])
    subgraph sys["AI Job Agent (self-hosted)"]
        agent["Job Agent system"]
    end
    naukri["Naukri.com<br/>website"]
    claude["Claude<br/>(via Claude Agent SDK,<br/>user's subscription)"]
    ollama["Ollama<br/>(local LLM fallback)"]

    user -- "profile.yaml, approve / reject" --> agent
    agent -- "ranked jobs, approval requests" --> user
    agent -- "Playwright: search, read, apply" --> naukri
    agent -- "evaluation prompt → JSON" --> claude
    agent -. "fallback prompt → JSON" .-> ollama

    classDef built fill:#d4edda,stroke:#2e7d32,color:#000
    classDef planned fill:#eeeeee,stroke:#888,stroke-dasharray:5 5,color:#000
    class agent,naukri,claude built
    class ollama planned
```

## 2. Containers — current (Built)

Everything runs in one Python process started by `python main.py`; Postgres and Qdrant run in
Docker Compose.

```mermaid
flowchart TB
    subgraph host["Developer machine"]
        subgraph proc["Python process: main.py"]
            app["app/ package<br/>pipeline, services, repository"]
            pw["Playwright + Chromium<br/>(headed by default)"]
            emb["fastembed<br/>bge-small-en-v1.5 (ONNX, CPU)"]
            sdk["claude-agent-sdk"]
        end
        subgraph compose["docker-compose.yml"]
            pg[("PostgreSQL 16<br/>:5433")]
            qd[("Qdrant v1.18.2<br/>:6333 / :6334")]
        end
    end
    naukri["Naukri.com"]
    claude["Claude"]

    app --> pw --> naukri
    app --> emb
    app -- "SQLAlchemy async / asyncpg" --> pg
    app -- "qdrant-client (sync HTTP)" --> qd
    app --> sdk --> claude

    classDef built fill:#d4edda,stroke:#2e7d32,color:#000
    class app,pw,emb,sdk,pg,qd built
```

Also in the repo but outside the main flow:

- `app/agent/` — **In progress**: Claude Agent SDK tool-calling prototype with a CLI approval prompt
  (`python -m app.agent.agent`). Duplicates part of the pipeline ([known issue](12-roadmap-and-status.md#known-issues)).
- `server.py` — an unrelated MCP-server experiment (`create_post` tool). Not part of the product.

## 3. Containers — target (Planned)

```mermaid
flowchart TB
    user(["Candidate"])
    subgraph host["Self-hosted (local machine / home server)"]
        dash["Next.js dashboard<br/>[Planned]"]
        api["FastAPI API<br/>[Planned]"]
        tsrv["Temporal server + UI<br/>[Planned]"]
        subgraph worker["Temporal worker (Python) [In progress]"]
            wf["Workflows<br/>Discovery / Application"]
            acts["Activities<br/>browser, match, persist"]
            pw["Playwright Chromium"]
            emb["fastembed"]
            llm["LLMProvider<br/>Claude SDK | Ollama"]
        end
        pg[("PostgreSQL<br/>[Built]")]
        qd[("Qdrant<br/>[Built]")]
        minio[("MinIO<br/>screenshots, HTML, resumes<br/>[Planned]")]
        obs["OTel Collector → Grafana stack<br/>+ Langfuse<br/>[Planned]"]
    end
    naukri["Naukri.com"]
    claude["Claude"]
    ollama["Ollama"]

    user --> dash --> api
    api -- "start workflow / send approval signal / query" --> tsrv
    tsrv <--> wf
    wf --> acts
    acts --> pw --> naukri
    acts --> emb
    acts --> llm
    llm --> claude
    llm -.-> ollama
    acts --> pg
    acts --> qd
    acts --> minio
    api --> pg
    worker -.-> obs
    api -.-> obs

    classDef built fill:#d4edda,stroke:#2e7d32,color:#000
    classDef planned fill:#eeeeee,stroke:#888,stroke-dasharray:5 5,color:#000
    class pg,qd built
    class dash,api,tsrv,wf,acts,pw,emb,llm,minio,obs planned
```

Key properties of the target:

- **One codebase, two entry points** (API + worker) — modular monolith ([ADR-011](adr/ADR-011-modular-monolith.md)).
- **The browser runs where the user is.** Headed Chromium needs a display, so the worker runs on
  the user's machine, not in a headless container, unless `BROWSER_HEADLESS=true`.
- **Approval is a Temporal signal** sent by the API; the submit activity is unreachable without it ([03](03-workflows.md)).
- **Postgres is the source of truth**; Qdrant and MinIO hold derived / binary data and can be rebuilt or re-captured.

## 4. Components of `app/` (current)

```mermaid
flowchart TB
    main["main.py<br/>entry point"]
    container["app/container.py<br/>manual DI factory"]
    config["app/config.py<br/>Settings (pydantic-settings)"]
    logcfg["app/logging_config.py<br/>structlog"]

    subgraph services["app/services — orchestration + domain logic"]
        pipe["JobMatchingPipeline"]
        disc["JobDiscoveryService"]
        filt["JobFilterService<br/>(hardcoded keywords)"]
        ranker["JobRanker<br/>(Qdrant)"]
        match["JobMatchService<br/>(prompt)"]
        score["JobScoreService<br/>50/30/20"]
        level["JobMatchLevelService"]
        rank["JobRankingService"]
        prof["profile_loader"]
    end

    subgraph sources["app/job_sources + app/browser — scraping"]
        js["JobSource (ABC)"]
        njs["NaukriJobSource"]
        ext["NaukriExtractor"]
        nb["NaukriBrowser"]
        ndf["fetch_job_page<br/>(detail page, logged out)"]
        ndp["parse_job_detail<br/>(JSON-LD → DOM fallback)"]
    end

    subgraph llm["app/llm"]
        ccp["ClaudeCodeProvider"]
    end

    subgraph vector["app/vector"]
        embd["Embedder"]
        store["JobVectorStore"]
        texts["texts.py"]
    end

    subgraph db["app/db"]
        repo["JobRepository"]
        models["JobRecord / JobMatchRecord"]
        dbconn["database.py<br/>engine, SessionLocal"]
    end

    subgraph models_p["app/models — Pydantic DTOs"]
        dto["Job, CandidateProfile,<br/>JobMatchResult, JobMatchItem"]
    end

    subgraph agent["app/agent — prototype (In progress)"]
        ag["agent.py + claude_tools.py<br/>approval.py, state.py, steps.py"]
    end

    main --> config & logcfg & prof & container
    main --> pipe
    main --> repo
    container --> pipe
    pipe --> disc --> js
    njs -. implements .-> js
    njs --> nb & ext
    ndf --> nb
    pipe --> filt & ranker & match & score & level & rank
    pipe --> repo --> models --> dbconn
    ranker --> embd & store & texts
    match --> ccp
    ag --> njs
    ag -.-> filt & score & level & rank

    classDef built fill:#d4edda,stroke:#2e7d32,color:#000
    classDef wip fill:#fff3cd,stroke:#b8860b,color:#000
    class main,container,config,logcfg,pipe,disc,filt,ranker,match,score,level,rank,prof,js,njs,ext,nb,ndf,ndp,ccp,embd,store,texts,repo,models,dbconn,dto built
    class ag wip
```

### Layer responsibilities

| Layer | Package | Responsibility | Status |
|---|---|---|---|
| Entry / composition | `main.py`, `app/container.py` | Load settings + profile, wire dependencies, print result | Built |
| Orchestration | `app/services/job_matching_pipeline.py` | Run the steps in order | Built (to be replaced by Temporal workflows) |
| Domain services | `app/services/*` | Filtering, scoring, levelling, ranking, prompt building | Built |
| Sources / browser | `app/job_sources/`, `app/browser/` | Get jobs from Naukri | Built (search cards; detail pages via the `fetch_job_details` activity on the `job-agent-browser` queue) |
| LLM | `app/llm/` | Call Claude and validate JSON | Built (no abstraction yet) |
| Retrieval | `app/vector/` | Embeddings + Qdrant | Built |
| Persistence | `app/db/`, `alembic/` | Tables, repository, migrations | Built |
| DTOs | `app/models/` | Pydantic models passed between layers | Built |
| API / UI | — | FastAPI, Next.js | Planned |
| Workflows | `app/workflows/` | Temporal workflows, activities, worker, client (Pydantic converter) | In progress (discovery + per-job application with approval; apply is dry-run) |

### Dependency rules (to keep as the code grows)

- `app/models` depends on nothing inside `app/`.
- Domain services must not import Playwright, SQLAlchemy, Qdrant or an LLM SDK directly; they get
  them through an interface (`JobSource`, `LLMProvider`, repository). *Currently violated by
  `JobMatchService`, which instantiates `ClaudeCodeProvider` itself (`app/services/job_match_service.py:11`).*
- Temporal workflow code must be deterministic: no I/O, no `datetime.now()`, no randomness
  — all of that lives in activities.

## 5. Current vs target — summary

| Concern | Current | Target |
|---|---|---|
| Trigger | Manual `python main.py` | Temporal Schedule → `JobDiscoveryWorkflow` |
| Orchestration | `JobMatchingPipeline.run()` in-process | Temporal workflows + activities |
| Job detail | Workflow path: detail page read after the filter (`jobs.description_full`, `jobs.details`); `main.py` path: snippet unless details were already stored | Same, plus a backfill for older jobs |
| Job state | Implicit (row in `jobs` / row in `job_matches`) | Explicit lifecycle state machine ([03](03-workflows.md#job-lifecycle-state-machine)) |
| LLM | `ClaudeCodeProvider` called directly, sequential | `LLMProvider` interface, timeouts, retries, bounded concurrency |
| Approval | CLI `input()` in prototype | Signal from dashboard/API with timeout |
| Apply | Not implemented | `submit_application` activity, dry-run first |
| Users | Single, implicit | `users` + `candidate_profiles` tables |
| Artifacts | None | MinIO (screenshots, page HTML) |
| Observability | structlog to stdout | OpenTelemetry + Grafana stack + Langfuse |
