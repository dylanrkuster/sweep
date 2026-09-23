"""Join predictions to their answer key only after evaluating an input."""

from collections.abc import Iterable
from dataclasses import dataclass
from time import perf_counter

from sweep.decisions.context import ContextError
from sweep.decisions.engine import Predictor, evaluate_decision
from sweep.decisions.policy import DecisionError, check_threshold
from sweep.domain import DecisionInput, Message
from sweep.testing.fixtures import EvaluationCase
from sweep.testing.mailbox import InMemoryMailbox


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    family_id: str
    split: str
    repetition: int
    expected_action: str | None
    expected_error: str | None
    action: str | None
    raw_choice: str | None
    probabilities: dict[str, float] | None
    error: str | None
    token_counts: dict[str, int] | None
    omissions: tuple[str, ...]
    normalizations: tuple[str, ...]
    context_seconds: float | None
    inference_seconds: float | None
    total_seconds: float

    @property
    def matches_expectation(self) -> bool:
        if self.expected_error is not None:
            return self.action is None and self.error == self.expected_error
        return self.error is None and self.action == self.expected_action


def run_cases(
    messages: Iterable[Message],
    cases: Iterable[EvaluationCase],
    predictor: Predictor,
    *,
    max_tokens: int = 2048,
    delete_threshold: float = 0.8,
    repetitions: int = 1,
) -> tuple[CaseResult, ...]:
    check_threshold(delete_threshold)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    mailbox = InMemoryMailbox(messages)
    cases = tuple(cases)
    results = []
    for repetition in range(1, repetitions + 1):
        for case in cases:
            mailbox.reset()
            decision_input = DecisionInput(
                preferences=case.preferences,
                current_message=mailbox.get_message(case.target_message_id),
                prior_messages=mailbox.get_prior_thread_messages(case.target_message_id),
            )
            start = perf_counter()
            outcome = None
            error_code = None
            failed_counts = None
            failed_omissions = ()
            failed_normalizations = ()
            failed_context_seconds = None
            failed_inference_seconds = None
            try:
                outcome = evaluate_decision(
                    decision_input, predictor, max_tokens=max_tokens,
                    delete_threshold=delete_threshold,
                )
            except (ContextError, DecisionError) as error:
                error_code = error.code
                failed_counts = getattr(error, "token_counts", None) or None
                failed_omissions = getattr(error, "omissions", ())
                failed_normalizations = getattr(error, "normalizations", ())
                failed_context_seconds = getattr(error, "context_seconds", None)
                failed_inference_seconds = getattr(error, "inference_seconds", None)
                failed_context = getattr(error, "context", None)
                if failed_context is not None:
                    failed_counts = dict(failed_context.token_counts)
                    failed_omissions = failed_context.omissions
                    failed_normalizations = failed_context.normalizations
            total_seconds = perf_counter() - start
            # Expected values are introduced here, after the model-facing path.
            results.append(CaseResult(
                case_id=case.case_id,
                family_id=case.family_id,
                split=case.split,
                repetition=repetition,
                expected_action=case.expected_action,
                expected_error=case.expected_error,
                action=outcome.decision.action if outcome else None,
                raw_choice=outcome.decision.raw_choice if outcome else None,
                probabilities={
                    "archive": outcome.decision.archive_probability,
                    "delete": outcome.decision.delete_probability,
                } if outcome else None,
                error=error_code,
                token_counts=dict(outcome.context.token_counts) if outcome else failed_counts,
                omissions=outcome.context.omissions if outcome else failed_omissions,
                normalizations=outcome.context.normalizations if outcome else failed_normalizations,
                context_seconds=outcome.context_seconds if outcome else failed_context_seconds,
                inference_seconds=outcome.inference_seconds if outcome else failed_inference_seconds,
                total_seconds=total_seconds,
            ))
    return tuple(results)
