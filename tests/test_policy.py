"""A malformed prediction must never become a successful mailbox action."""

import math

import pytest

from sweep.decisions.policy import DecisionError, apply_policy, check_threshold


@pytest.mark.parametrize(
    ("delete_probability", "choice", "expected"),
    [(0.5, "archive", "archive"), (0.5, "delete", "archive"),
     (0.7999, "delete", "archive"), (0.8, "delete", "delete"),
     (1.0, "delete", "delete")],
)
def test_policy_keeps_raw_choice_and_applies_the_delete_threshold(
    delete_probability, choice, expected
):
    result = apply_policy({
        "choice": choice,
        "probabilities": {"archive": 1 - delete_probability, "delete": delete_probability},
        "confidence": 1.0,
        "act_probability": 1.0,
    }, 0.8)

    assert result.action == expected
    assert result.raw_choice == choice
    assert result.delete_probability == delete_probability
    assert result.archive_probability == 1 - delete_probability


@pytest.mark.parametrize("prediction", [
    None,
    {},
    {"choice": "delete", "probabilities": {"delete": 1.0}},
    {"choice": "delete", "probabilities": {"archive": 0, "delete": 1, "keep": 0}},
    {"choice": "keep", "probabilities": {"archive": 0.5, "delete": 0.5}},
    {"choice": "archive", "probabilities": {"archive": 0.1, "delete": 0.9}},
    {"choice": "delete", "probabilities": {"archive": 0.4, "delete": 0.4}},
    {"choice": "delete", "probabilities": {"archive": 0, "delete": True}},
    {"choice": "delete", "probabilities": {"archive": 0, "delete": "1.0"}},
    {"choice": "delete", "probabilities": {"archive": -0.1, "delete": 1.1}},
    {"choice": "delete", "probabilities": {"archive": 0, "delete": math.nan}},
    {"choice": "delete", "probabilities": {"archive": 0, "delete": math.inf}},
])
def test_invalid_predictions_raise_an_explicit_error(prediction):
    with pytest.raises(DecisionError) as error:
        apply_policy(prediction, 0.8)
    assert error.value.code == "invalid_model_output"


@pytest.mark.parametrize("threshold", [True, 0, 0.5, 1.01, math.nan, math.inf, "0.8"])
def test_invalid_thresholds_are_configuration_errors(threshold):
    with pytest.raises(ValueError, match="delete threshold"):
        check_threshold(threshold)


def test_full_certainty_can_be_required_without_rejecting_the_threshold():
    result = apply_policy({
        "choice": "delete", "probabilities": {"archive": 0, "delete": 1},
    }, 1.0)
    assert result.action == "delete"
