from pathlib import Path

import yaml

from app.models.application_answers import ApplicationAnswers


def load_answers(path: Path) -> ApplicationAnswers:
    """Load and validate answers.yaml; bad values fail here, not mid-application."""

    if not path.exists():
        raise FileNotFoundError(
            f"Answers file not found: {path}. "
            "Copy answers.example.yaml to answers.yaml and fill it in."
        )

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return ApplicationAnswers.model_validate(data)
