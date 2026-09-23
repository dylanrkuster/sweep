"""Count errors separately so always archiving cannot look like useful deletion."""

import math
import statistics
from collections import Counter
from collections.abc import Iterable

from sweep.evaluation.runner import CaseResult


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def summarize(results: Iterable[CaseResult], *, raw: bool = False) -> dict:
    rows = tuple(results)
    matrix = {expected: {actual: 0 for actual in ("archive", "delete", "error")}
              for expected in ("archive", "delete")}
    for row in rows:
        if row.expected_action in matrix:
            actual = row.raw_choice if raw else row.action
            matrix[row.expected_action][actual if actual is not None else "error"] += 1
    correct_deletes = matrix["delete"]["delete"]
    predicted_deletes = sum((r.raw_choice if raw else r.action) == "delete" for r in rows)
    expected_deletes = sum(r.expected_action == "delete" for r in rows)
    return {
        "attempts": len(rows),
        "unique_cases": len({r.case_id for r in rows}),
        "families": len({r.family_id for r in rows}),
        "expected_actions": dict(Counter(r.expected_action for r in rows if r.expected_action)),
        "predicted_actions": dict(Counter((r.raw_choice if raw else r.action) for r in rows
                                          if (r.raw_choice if raw else r.action))),
        "errors": dict(Counter(r.error for r in rows if r.error)),
        "expected_error_cases": sum(r.expected_error is not None for r in rows),
        "expected_errors_matched": sum(r.expected_error is not None and r.matches_expectation for r in rows),
        "unexpected_errors": sum(r.error is not None and r.error != r.expected_error for r in rows),
        "confusion_matrix": matrix,
        "action_accuracy": _ratio(matrix["archive"]["archive"] + correct_deletes,
                                  sum(r.expected_action is not None for r in rows)),
        "false_deletes": sum((r.raw_choice if raw else r.action) == "delete"
                             and r.expected_action != "delete" for r in rows),
        "delete_precision": _ratio(correct_deletes, predicted_deletes),
        "delete_recall": _ratio(correct_deletes, expected_deletes),
    }


def timing_summary(results: Iterable[CaseResult]) -> dict:
    rows = tuple(results)
    inference = [r.inference_seconds for r in rows if r.inference_seconds is not None]
    context = [r.context_seconds for r in rows if r.context_seconds is not None]
    # Failed calls still count: they can warm the model before the next call.
    warm = sorted(inference[1:])
    return {
        "first_inference_seconds": inference[0] if inference else None,
        "warm_inference_count": len(warm),
        "warm_median_seconds": statistics.median(warm) if warm else None,
        "warm_p95_seconds": warm[math.ceil(0.95 * len(warm)) - 1] if warm else None,
        "context_median_seconds": statistics.median(context) if context else None,
        "case_total_seconds": sum(r.total_seconds for r in rows),
        "method": "perf_counter wall time; first inference attempt excluded from warm; failed calls included; nearest-rank p95",
    }
