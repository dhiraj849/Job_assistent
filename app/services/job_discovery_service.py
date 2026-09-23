from app.job_sources.base import JobSource
from app.models.job import Job


class JobDiscoveryService:

    def __init__(self, job_source: JobSource):
        self.job_source = job_source

    async def get_jobs(self) -> list[Job]:

        return await self.job_source.get_jobs()