from app.models.job_match_item import JobMatchItem


class JobRankingService:

    def rank(
        self,
        matches: list[JobMatchItem]
    ) -> list[JobMatchItem]:

        return sorted(
            matches,
            key=lambda item: (
                item.overall_score,
                item.match.skill_match,
                item.match.role_match,
                item.match.experience_match
            ),
            reverse=True
        )