"""Start one discovery run now (search -> save -> one application workflow per new job).

The old in-process pipeline is gone: Temporal workflows do the whole flow,
respect jobs.status and wait for my approval. Needs infra + a running worker:
  docker compose up -d
  uv run python -m app.workflows.worker

Usage: uv run python main.py   (same as scripts/start_discovery.py with the profile's search)
Scheduled runs: scripts/schedule_discovery.py
"""

import asyncio

from app.config import settings
from app.services.profile_loader import load_profile
from scripts.start_discovery import main as start_discovery

if __name__ == "__main__":
    search = load_profile(settings.PROFILE_PATH).search
    asyncio.run(start_discovery(search.keyword, search.location))
