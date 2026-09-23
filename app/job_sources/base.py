from abc import ABC, abstractmethod

from app.models.job import Job


class JobSource(ABC):

    @abstractmethod
    async def get_jobs(self) -> list[Job]:
        pass