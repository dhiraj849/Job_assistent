from pathlib import Path

import yaml

from app.models.candidate_profile import CandidateProfile


def load_profile(path: Path) -> CandidateProfile:

    if not path.exists():
        raise FileNotFoundError(
            f"Profile file not found: {path}. "
            "Copy profile.example.yaml to profile.yaml and fill it in."
        )

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return CandidateProfile.model_validate(data)