from dataclasses import dataclass, field

from app.models.candidate_profile import CandidateProfile
from app.models.job import Job
from app.models.job_match_item import JobMatchItem


@dataclass
class AgentState:

    candidate: CandidateProfile

    jobs: list[Job] = field(default_factory=list)
    current_job: Job | None = None
    matches: list[JobMatchItem] = field(
        default_factory=list
    )

    ranked_jobs: list[JobMatchItem] = field(
        default_factory=list
    )
    
    approval_status: str = "pending"

    next_action: str = "review"