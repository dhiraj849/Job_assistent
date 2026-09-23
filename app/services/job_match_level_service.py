class JobMatchLevelService:

    STRONG_THRESHOLD = 80
    POTENTIAL_THRESHOLD = 60

    def classify(self, overall_score: int) -> str:

        if overall_score >= self.STRONG_THRESHOLD:
            return "strong"

        if overall_score >= self.POTENTIAL_THRESHOLD:
            return "potential"

        return "weak"