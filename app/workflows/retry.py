from datetime import timedelta

from temporalio.common import RetryPolicy

# Shared by all activities: flaky network, page loads or LLM hiccups get a
# few retries with growing gaps instead of hammering Naukri / the LLM.
RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)
