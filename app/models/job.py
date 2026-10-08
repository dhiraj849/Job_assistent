from pydantic import BaseModel

from app.models.job_details import JobDetails


class Job(BaseModel):

    title: str
    company: str
    location: str

    experience: str | None = None
    salary: str | None = None

    # Full JD once the detail page was read, else the search-card snippet.
    description: str

    skills: list[str] = []

    url: str | None = None

    # None until fetch_job_details has read the detail page.
    details: JobDetails | None = None
