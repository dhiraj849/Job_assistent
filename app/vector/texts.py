MAX_DESCRIPTION_CHARS = 1500


def job_to_text(title, skills, description):
    """The text we embed for a job."""
    parts = [title]

    if skills:
        parts.append("Skills: " + ", ".join(skills))

    if description:
        parts.append(description[:MAX_DESCRIPTION_CHARS])

    return "\n".join(parts)


def profile_to_text(candidate):
    """The text we embed for the candidate profile."""
    return (
        f"{candidate.experience_years} years of experience. "
        f"Skills: {', '.join(candidate.skills)}."
    )