from pydantic import BaseModel


class Job(BaseModel):

    title: str
    company: str
    location: str

    experience: str | None = None
    salary: str | None = None

    description: str

    skills: list[str] = []

    url: str | None = None