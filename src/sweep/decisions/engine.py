"""Run the same single-email decision path in evaluations and future workers."""

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from sweep.decisions.context import ContextError, PreparedContext, build_context
from sweep.decisions.policy import PolicyDecision, DecisionError, apply_policy
from sweep.domain import DecisionInput


class Predictor(Protocol):
    tokenizer: Any

    def predict(self, context: PreparedContext) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    decision: PolicyDecision
    context: PreparedContext
    context_seconds: float
    inference_seconds: float


def evaluate_decision(
    decision_input: DecisionInput,
    predictor: Predictor,
    *,
    max_tokens: int = 2048,
    delete_threshold: float = 0.8,
) -> DecisionOutcome:
    start = perf_counter()
    try:
        context = build_context(decision_input, predictor.tokenizer, max_tokens=max_tokens)
    except ContextError as error:
        error.context_seconds = perf_counter() - start
        raise
    context_seconds = perf_counter() - start
    start = perf_counter()
    try:
        prediction = predictor.predict(context)
    except Exception as error:
        # Model exceptions may include input text; public diagnostics use codes.
        raise DecisionError("inference_failed", "Model inference failed", context=context,
                            context_seconds=context_seconds,
                            inference_seconds=perf_counter() - start) from error
    inference_seconds = perf_counter() - start
    try:
        decision = apply_policy(prediction, delete_threshold)
    except DecisionError as error:
        error.context = context
        error.context_seconds = context_seconds
        error.inference_seconds = inference_seconds
        raise
    return DecisionOutcome(decision, context, context_seconds, inference_seconds)
