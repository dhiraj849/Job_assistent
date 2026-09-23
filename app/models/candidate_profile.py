from pydantic import BaseModel


class CandidateProfile(BaseModel):
    name: str
    experience_years: int
    skills: list[str]
    education: str
