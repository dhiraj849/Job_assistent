import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Simple shape checks, no new dependency: a typo must fail at load time,
# not be typed into a company's form.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[\d\s-]+$")
RESUME_SUFFIXES = (".pdf", ".doc", ".docx")


class ContactAnswers(BaseModel):
    """Contact details for company career-site forms (answers.yaml "contact:")."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: str
    # As it should be typed, e.g. "+91 98765 43210".
    phone: str
    # Checked for existence when a form is filled, not here: the example file
    # must load on any machine.
    resume_path: Path
    linkedin_url: str = ""

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        if not _EMAIL.match(value):
            raise ValueError("email does not look like an email address")
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        if not _PHONE.match(value) or sum(c.isdigit() for c in value) < 10:
            raise ValueError("phone must be digits (optional +, spaces, -) with at least 10 digits")
        return value

    @field_validator("resume_path")
    @classmethod
    def _check_resume(cls, value: Path) -> Path:
        if value.suffix.lower() not in RESUME_SUFFIXES:
            raise ValueError(f"resume_path must end with one of {RESUME_SUFFIXES}")
        return value

    @field_validator("linkedin_url")
    @classmethod
    def _check_linkedin(cls, value: str) -> str:
        if value and not value.startswith("https://"):
            raise ValueError("linkedin_url must start with https://")
        return value

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class ApplicationAnswers(BaseModel):
    """Standard answers for apply questions and forms, loaded from answers.yaml."""

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
    # Only needed for company career sites; Naukri applies work without it.
    contact: ContactAnswers | None = None

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
