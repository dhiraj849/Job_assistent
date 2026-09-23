from pydantic import BaseModel

from app.models.job import Job
from app.models.job_match import JobMatchResult


class JobMatchItem(BaseModel):

    job: Job

    match: JobMatchResult

    overall_score: int

    match_level: str