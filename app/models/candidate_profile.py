from pydantic import BaseModel, Field


class SearchConfig(BaseModel):
    """What to search for and how to pre-filter it.

    Lives in the profile YAML (no defaults here), so the filter and the
    LLM role focus can never silently differ from what I wrote there.
    """

    # Default search for discovery runs, scripts and the agent
    keyword: str = Field(min_length=1)
    location: str = Field(min_length=1)

    # A title with any of these is relevant on its own
    title_keywords: list[str] = Field(min_length=1)

    # Broad titles ("software engineer") that count only with a supporting skill
    generic_titles: list[str] = Field(min_length=1)

    # Job skills that back up a generic title
    supporting_skills: list[str] = Field(min_length=1)

    # A title with any of these is dropped, even if a keyword matches
    exclude_title_keywords: list[str]

    # "The candidate is primarily interested in" lines for the LLM prompt
    role_focus: list[str] = Field(min_length=1)


class CandidateProfile(BaseModel):
    name: str
    experience_years: int = Field(ge=0)
    skills: list[str]
    education: str
    search: SearchConfig
