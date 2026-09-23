class JobScoreService:

    SKILL_WEIGHT = 0.50
    ROLE_WEIGHT = 0.30
    EXPERIENCE_WEIGHT = 0.20

    def calculate(
        self,
        skill_match: int,
        role_match: int,
        experience_match: int
    ) -> int:

        score = (
            skill_match * self.SKILL_WEIGHT
            + role_match * self.ROLE_WEIGHT
            + experience_match * self.EXPERIENCE_WEIGHT
        )

        return round(score)