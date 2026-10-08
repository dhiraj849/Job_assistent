from datetime import date
from typing import Literal

from pydantic import BaseModel


class JobDetails(BaseModel):
    """Extra facts from a job's detail page (stored in jobs.details, JSONB).

    Every field is optional: Naukri leaves many of them out, and a missing
    fact must never block a job.
    """

    # Where the data came from: "json_ld" (full) or "dom" (fallback, JD text only).
    source: Literal["json_ld", "dom"]

    skills: list[str] = []
    # Naukri's own text, e.g. "15-25 Lacs P.A."; None when "Not disclosed".
    salary: str | None = None
    experience_months: int | None = None
    employment_type: str | None = None
    industry: str | None = None
    department: str | None = None
    role: str | None = None
    education: str | None = None
    date_posted: date | None = None
    valid_through: date | None = None


class JobDetailPage(BaseModel):
    """What the parser reads from one detail page."""

    # Plain text (HTML stripped), stored in jobs.description_full.
    description: str
    details: JobDetails
