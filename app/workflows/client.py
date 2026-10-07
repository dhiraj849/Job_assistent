from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from app.config import settings


async def connect_client() -> Client:
    """Connect to Temporal. Every client (worker AND scripts) must use this,

    because the worker and its callers need the same data converter:
    the Pydantic converter lets activities take and return our models.
    """
    return await Client.connect(
        settings.TEMPORAL_ADDRESS,
        namespace=settings.TEMPORAL_NAMESPACE,
        data_converter=pydantic_data_converter,
    )
