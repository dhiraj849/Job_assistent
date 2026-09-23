from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    name: str
    experience_years: int = Field(ge=0)
    skills: list[str]
    education: str
