from app.llm.claude_code import ClaudeCodeProvider
from app.models.job_match import JobMatchResult
from app.models.candidate_profile import CandidateProfile
from app.models.job import Job


class JobMatchService:

    def __init__(self):

        self.llm = ClaudeCodeProvider()

    async def match(
        self,
        candidate_profile: CandidateProfile,
        job: Job
    ) -> JobMatchResult:

        prompt = f"""
You are a job matching system.

Your task is to evaluate how well the job matches the candidate.

Do not calculate an overall score.
The application calculates the overall score separately.

----------------------------------------
CANDIDATE
----------------------------------------

{candidate_profile.model_dump()}

----------------------------------------
JOB
----------------------------------------

{job.model_dump()}

----------------------------------------
SCORING RULES
----------------------------------------

ROLE MATCH:

Evaluate how closely the job role matches the candidate's
target profile.

The candidate is primarily interested in:

- Python backend development
- Django
- FastAPI
- REST APIs
- AI / GenAI backend roles

Scoring guidance:

90-100:
Very strong role alignment.

70-89:
Strong role alignment with minor differences.

50-69:
Partially related role.

30-49:
Weak role alignment.

0-29:
Mostly unrelated role.

----------------------------------------

SKILL MATCH:

Compare the candidate's skills with the technical requirements
of the job.

Consider:

- Direct skill matches
- Related technologies
- Missing important skills
- Core versus secondary requirements

Scoring guidance:

90-100:
Most important skills match.

70-89:
Good skill overlap with some gaps.

50-69:
Moderate overlap.

30-49:
Limited overlap.

0-29:
Very little technical overlap.

----------------------------------------

EXPERIENCE MATCH:

Compare the candidate's experience with the job's
experience requirement.

Candidate experience:

{candidate_profile.experience_years} years

Consider whether the candidate:

- Meets the requirement
- Is slightly below the requirement
- Has significantly less experience
- Has more experience than required

Scoring guidance:

90-100:
Experience requirement is clearly satisfied.

70-89:
Small difference between candidate and requirement.

50-69:
Moderate difference.

30-49:
Significant difference.

0-29:
Experience requirement is substantially different.

----------------------------------------
IMPORTANT
----------------------------------------

Do not assume missing information.

If the job does not clearly specify a requirement,
do not invent one.

Do not treat every technology as equally important.

Focus more heavily on core job requirements.

Return:

- role_match
- skill_match
- experience_match
- matching_skills
- missing_skills
- strengths
- concerns
- recommendation

All three scores must be integers between 0 and 100.

Do not return an overall score.
"""

        return await self.llm.generate(prompt)