# Job Agent: one-command control of the local stack.
# Run `make` (or `make help`) to list targets.

SHELL := /bin/bash
# Each recipe runs in ONE bash process with strict mode, so the first
# failing command stops the whole target (set -e style).
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL := help

RUN_DIR     := .run
WORKER_PID  := $(RUN_DIR)/worker.pid
WORKER_LOG  := $(RUN_DIR)/worker.log
WAIT_SECS   := 60

TEMPORAL_UI := http://localhost:8080
QDRANT_UI   := http://localhost:6333/dashboard

.PHONY: help setup start stop down worker discover logs status pending approve reject

# Show every target that has a "##" description.
help: ## Show this help
	@echo "Job Agent - make targets:"
	awk -F':.*## ' '/^[a-zA-Z_-]+:.*## / {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# One-time setup: Python deps and the Chromium browser Playwright drives.
setup: ## One-time: uv sync + install Playwright Chromium
	uv sync
	uv run playwright install chromium

# Bring up infra, migrate, start the worker in the background, then run discovery.
start: ## Start everything: infra, migrations, worker, discovery
	@echo "==> Checking prerequisites"
	for tool in docker uv; do
	  command -v "$$tool" >/dev/null || { echo "ERROR: '$$tool' not found on PATH."; exit 1; }
	done
	# claude-agent-sdk shells out to the `claude` CLI, which lives in nvm's Node.
	command -v claude >/dev/null || {
	  echo "ERROR: 'claude' CLI not found on PATH (needed by claude-agent-sdk)."
	  echo "       Node comes from nvm. Run: nvm alias default 20   then open a new terminal."
	  exit 1
	}
	[ -f .env ] || { echo "ERROR: .env not found. Run: cp .env.example .env  and fill in the values."; exit 1; }

	echo "==> Starting Docker services"
	docker compose up -d

	echo "==> Waiting for services (timeout $(WAIT_SECS)s)"
	# Poll a check command until it passes or the deadline hits (no blind sleep).
	wait_for() {
	  local name="$$1"; shift
	  local deadline=$$((SECONDS + $(WAIT_SECS)))
	  until "$$@" >/dev/null 2>&1; do
	    if (( SECONDS >= deadline )); then
	      echo "ERROR: $$name not ready after $(WAIT_SECS)s. Check: docker compose logs"; exit 1
	    fi
	    sleep 2
	  done
	  echo "    $$name is ready"
	}
	# TCP check via 127.0.0.1: during first-time init Postgres only listens on
	# its socket, so this passes only once the real server is up.
	wait_for Postgres docker compose exec -T postgres pg_isready -q -h 127.0.0.1
	wait_for Qdrant curl -sf http://localhost:6333/readyz
	wait_for Temporal nc -z localhost 7233
	# The "default" namespace is created by a one-shot container; workflows fail without it.
	namespace_done() { [ "$$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' job_agent_temporal_namespace)" = "exited 0" ]; }
	wait_for "Temporal namespace" namespace_done

	echo "==> Syncing Python deps"
	uv sync

	echo "==> Running migrations"
	uv run alembic upgrade head

	echo "==> Starting worker"
	mkdir -p $(RUN_DIR)
	if [ -f $(WORKER_PID) ] && kill -0 "$$(cat $(WORKER_PID))" 2>/dev/null; then
	  echo "    Worker already running (PID $$(cat $(WORKER_PID))), not starting another"
	else
	  rm -f $(WORKER_PID)
	  : > $(WORKER_LOG)
	  # setsid gives the worker its own process group, so `make stop` can
	  # kill uv AND the python child together.
	  # PYTHONUNBUFFERED: write log lines immediately, so `make logs` is live.
	  PYTHONUNBUFFERED=1 setsid nohup uv run python -m app.workflows.worker >> $(WORKER_LOG) 2>&1 < /dev/null &
	  echo $$! > $(WORKER_PID)
	  pid=$$(cat $(WORKER_PID))
	  # Ready = still alive after 10s. We can't wait for the "worker_started"
	  # line: under `python -m` its logger is "__main__", which drops INFO.
	  for _ in $$(seq 1 10); do
	    kill -0 "$$pid" 2>/dev/null || break
	    sleep 1
	  done
	  if ! kill -0 "$$pid" 2>/dev/null; then
	    echo "ERROR: worker did not start. Last 30 log lines:"
	    tail -n 30 $(WORKER_LOG)
	    kill -TERM -- -"$$pid" 2>/dev/null || true
	    rm -f $(WORKER_PID)
	    exit 1
	  fi
	  echo "    Worker started (PID $$pid)"
	fi

	# Print URLs before discovery: discovery blocks until the workflow finishes.
	echo
	echo "Temporal UI : $(TEMPORAL_UI)"
	echo "Qdrant UI   : $(QDRANT_UI)"
	echo "Worker logs : make logs   (or: tail -f $(WORKER_LOG))"
	echo

	echo "==> Running discovery (waits until the workflow finishes)"
	uv run python -m scripts.start_discovery
	echo "Done. Next: make pending"

# Stop the background worker (whole process group), then stop containers.
stop: ## Stop the worker and Docker services (keeps containers + data)
	@if [ -f $(WORKER_PID) ]; then
	  pid=$$(cat $(WORKER_PID))
	  if kill -0 "$$pid" 2>/dev/null; then
	    echo "==> Stopping worker (PID $$pid)"
	    kill -TERM -- -"$$pid" 2>/dev/null || kill -TERM "$$pid"
	    # Give Temporal a moment to finish in-flight work, then force it.
	    for _ in $$(seq 1 10); do kill -0 "$$pid" 2>/dev/null || break; sleep 1; done
	    kill -0 "$$pid" 2>/dev/null && kill -KILL -- -"$$pid" 2>/dev/null || true
	  else
	    echo "==> Removing stale PID file"
	  fi
	  rm -f $(WORKER_PID)
	else
	  echo "==> Worker not running"
	fi
	echo "==> Stopping Docker services"
	docker compose stop

# Stop everything and remove containers. Never uses -v, so volumes (data) stay.
down: stop ## Stop + remove containers (volumes/data are kept)
	docker compose down

# Run the worker in this terminal; Ctrl+C to stop. Useful for debugging.
worker: ## Run the worker in the foreground
	uv run python -m app.workflows.worker

# Only trigger discovery; assumes infra + worker are already running.
discover: ## Trigger job discovery (stack must be running)
	uv run python -m scripts.start_discovery

# Follow the background worker's log.
logs: ## Tail the worker log
	tail -f $(WORKER_LOG)

# Container status plus whether the background worker is alive.
status: ## Show Docker services and worker status
	@docker compose ps
	echo
	if [ -f $(WORKER_PID) ] && kill -0 "$$(cat $(WORKER_PID))" 2>/dev/null; then
	  echo "Worker: running (PID $$(cat $(WORKER_PID)))"
	elif [ -f $(WORKER_PID) ]; then
	  echo "Worker: not running (stale PID file $(WORKER_PID))"
	else
	  echo "Worker: not running"
	fi

# List jobs waiting for a human decision.
pending: ## List jobs awaiting approval
	uv run python -m scripts.list_pending

# Approve a job: make approve ID=42 [NOTE="looks good"]
approve: ## Approve a job: make approve ID=<id> [NOTE="..."]
	@[ -n "$(ID)" ] || { echo "ERROR: ID is required. Usage: make approve ID=<job_id>"; exit 1; }
	uv run python -m scripts.decide_job "$(ID)" yes "$(NOTE)"

# Reject a job: make reject ID=42 [NOTE="too junior"]
reject: ## Reject a job: make reject ID=<id> [NOTE="..."]
	@[ -n "$(ID)" ] || { echo "ERROR: ID is required. Usage: make reject ID=<job_id>"; exit 1; }
	uv run python -m scripts.decide_job "$(ID)" no "$(NOTE)"
