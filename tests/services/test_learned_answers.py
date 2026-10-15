import pytest
from pydantic import ValidationError

from app.services.learned_answers import (
    SIMILAR_MIN_SCORE,
    LearnedAnswers,
    label_key,
    learned_answers_path,
    load_learned,
    save_learned,
    similar_answers,
)


def test_label_key_ignores_case_marks_and_spacing():
    assert label_key("  Highest Qualification *: ") == label_key("highest qualification") == "highest qualification"


def test_missing_file_is_empty(tmp_path):
    assert load_learned(tmp_path / "learned_answers.yaml").answers == {}


def test_save_and_load_round_trip(tmp_path):
    path = learned_answers_path(tmp_path / "answers.yaml")
    learned = LearnedAnswers()
    learned.add("Highest Qualification*", "B.Tech")

    save_learned(path, learned)

    assert path.name == "learned_answers.yaml"
    assert load_learned(path).get("highest qualification") == "B.Tech"
    assert not path.with_suffix(".yaml.tmp").exists()


def test_unknown_keys_fail_loudly(tmp_path):
    path = tmp_path / "learned_answers.yaml"
    path.write_text("answer:\n  x: y\n")  # typo of "answers"
    with pytest.raises(ValidationError):
        load_learned(path)


# --- Related labels (similar_answers) ------------------------------------------------

# Fake embeddings: labels that mean the same point the same way.
_VECTORS = {
    "years of experience": [1.0, 0.1, 0.0],
    "total experience": [1.0, 0.0, 0.0],
    "relevant experience": [0.8, 0.6, 0.0],
    "current employer": [0.0, 0.0, 1.0],
}


def fake_embed(texts):
    return [_VECTORS[text] for text in texts]


def learned_with(**answers):
    learned = LearnedAnswers()
    for label, value in answers.items():
        learned.add(label.replace("_", " "), value)
    return learned


def test_related_label_gives_ranked_candidates():
    learned = learned_with(total_experience="5-8 Years", relevant_experience="3+ Years", current_employer="Acme")

    found = similar_answers("Years of experience", learned, fake_embed)

    # Best first; "current employer" is unrelated (score 0) and left out.
    assert [(f.label, f.value) for f in found] == [("total experience", "5-8 Years"), ("relevant experience", "3+ Years")]
    assert found[0].score > found[1].score >= SIMILAR_MIN_SCORE


def test_candidate_must_fit_the_options():
    learned = learned_with(total_experience="5-8 years", relevant_experience="3+ Years")

    found = similar_answers("Years of experience", learned, fake_embed, options=("Select", "5-8 Years", "10+ Years"))

    assert [(f.label, f.value) for f in found] == [("total experience", "5-8 Years")]


def test_exact_label_and_empty_store_give_nothing():
    assert similar_answers("Total Experience", learned_with(total_experience="5-8 Years"), fake_embed) == []
    assert similar_answers("Total Experience", LearnedAnswers(), fake_embed) == []


def test_same_value_is_offered_once():
    learned = learned_with(total_experience="5-8 Years", relevant_experience="5-8 Years")
    assert [f.label for f in similar_answers("Years of experience", learned, fake_embed)] == ["total experience"]


def test_typed_field_only_gets_values_of_its_shape():
    """zaax.com: "Landline Number" scored 0.71 against "current address"."""
    learned = learned_with(total_experience="Noida, India", relevant_experience="+91 120 4567890")
    found = similar_answers("Years of experience", learned, fake_embed, kind="tel")
    assert [f.value for f in found] == ["+91 120 4567890"]
