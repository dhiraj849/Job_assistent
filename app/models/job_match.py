from pydantic import BaseModel, Field


class JobMatchResult(BaseModel):

    role_match: int = Field(
        ge=0,
        le=100
    )

    skill_match: int = Field(
        ge=0,
        le=100
    )

    experience_match: int = Field(
        ge=0,
        le=100
    )

    matching_skills: list[str]

    missing_skills: list[str]

    strengths: list[str]

    concerns: list[str]

    recommendation: str