"""Validate one binary model prediction before applying an explicit policy."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Action = Literal["archive", "delete"]
POLICY_VERSION = "delete-threshold-v1"


class DecisionError(ValueError):
    def __init__(self, code: str, message: str, *, context: Any = None,
                 context_seconds: float | None = None, inference_seconds: float | None = None) -> None:
        self.code = code
        self.context = context
        self.context_seconds = context_seconds
        self.inference_seconds = inference_seconds
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    raw_choice: Action
    archive_probability: float
    delete_probability: float
    action: Action


def check_threshold(delete_threshold: float) -> None:
    if (
        isinstance(delete_threshold, bool)
        or not isinstance(delete_threshold, (int, float))
        or not math.isfinite(delete_threshold)
        or not 0.5 < delete_threshold <= 1.0
    ):
        raise ValueError("delete threshold must be greater than 0.5 and at most 1")


def apply_policy(prediction: Mapping[str, object], delete_threshold: float) -> PolicyDecision:
    """Archive ambiguous valid scores; malformed output is never a success.

    The threshold is experimental, not a calibrated probability of correctness.
    """
    check_threshold(delete_threshold)

    def invalid() -> DecisionError:
        return DecisionError("invalid_model_output", "Model output is not a consistent binary prediction")

    if not isinstance(prediction, Mapping):
        raise invalid()
    probabilities = prediction.get("probabilities")
    choice = prediction.get("choice")
    if not isinstance(probabilities, Mapping) or set(probabilities) != {"archive", "delete"}:
        raise invalid()
    values = [probabilities["archive"], probabilities["delete"]]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
        for value in values
    ):
        raise invalid()
    archive, delete = map(float, values)
    if choice not in ("archive", "delete") or not math.isclose(archive + delete, 1, abs_tol=1e-5):
        raise invalid()
    chosen = archive if choice == "archive" else delete
    if chosen < max(archive, delete) - 1e-6:
        raise invalid()
    action: Action = "delete" if delete >= delete_threshold else "archive"
    return PolicyDecision(choice, archive, delete, action)
