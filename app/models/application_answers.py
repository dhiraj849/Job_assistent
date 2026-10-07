from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApplicationAnswers(BaseModel):
    """Standard answers for Naukri apply questions, loaded from answers.yaml."""

    # Reject unknown keys so a typo (e.g. "notice_peroid_days") fails loudly
    # instead of silently leaving the real field at a wrong value.
    model_config = ConfigDict(extra="forbid")

    notice_period_days: int = Field(ge=0)
    current_ctc_lpa: float = Field(gt=0)
    expected_ctc_lpa: float = Field(gt=0)
    current_location: str = Field(min_length=1)
    willing_to_relocate: bool
    total_experience_years: float = Field(ge=0)
    skill_years: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_values(self) -> "ApplicationAnswers":
        # A lower expected CTC is almost always a typo, and it would be sent to recruiters.
        if self.expected_ctc_lpa < self.current_ctc_lpa:
            raise ValueError("expected_ctc_lpa must be >= current_ctc_lpa")
        for skill, years in self.skill_years.items():
            if years < 0:
                raise ValueError(f"skill_years[{skill!r}] must be >= 0")
        return self

    def skill_years_for(self, skill: str) -> float | None:
        """Years for a skill, case-insensitive ("Python" == "python"); None if not listed."""
        wanted = skill.strip().lower()
        for name, years in self.skill_years.items():
            if name.strip().lower() == wanted:
                return years
        return None
