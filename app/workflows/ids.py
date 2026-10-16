"""Workflow IDs shared by the scripts that start workflows."""

import re


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def discovery_workflow_id(keyword: str, location: str) -> str:
    # Stable per search: Temporal refuses a second run with the same ID
    # while one is open. A Schedule appends "-<scheduled time>" to it.
    return f"discovery-{slugify(keyword)}-{slugify(location)}"
