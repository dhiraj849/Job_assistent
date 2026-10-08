"""Task queue names that workflow code needs (plain constants: deterministic)."""

# Activities that open Naukri pages for reading. A separate queue whose
# worker runs ONE activity at a time, so we never hit Naukri with parallel
# browsers. Waiting tasks sit on the Temporal server, not in a worker slot,
# so LLM and DB activities on the main queue are not held up.
BROWSER_TASK_QUEUE = "job-agent-browser"
