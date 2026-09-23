"""Exercise evaluation and reporting with a predictor that needs no model."""

from dataclasses import replace
import json
import re
import subprocess
import sys

import pytest

from sweep.domain import Message
from sweep.evaluation.metrics import summarize, timing_summary
from sweep.evaluation.reports import write_reports
from sweep.evaluation.runner import CaseResult, run_cases
from sweep.testing.fixtures import EvaluationCase


class WordTokenizer:
    cls_token, sep_token, mask_token = "[CLS]", "[SEP]", "[MASK]"
    cls_token_id, sep_token_id, mask_token_id = 1, 2, 3
    all_special_tokens = (cls_token, sep_token, mask_token)

    def __init__(self):
        self.vocabulary = dict(zip(self.all_special_tokens, (1, 2, 3)))

    def encode(self, text, *, add_special_tokens=False):
        assert not add_special_tokens
        pieces = re.findall(r"\[CLS\]|\[SEP\]|\[MASK\]|\w+|[^\w\s]", text)
        return [self.vocabulary.setdefault(piece, len(self.vocabulary) + 1) for piece in pieces]


class RecordingPredictor:
    def __init__(self, prediction=None, error=None):
        self.tokenizer = WordTokenizer()
        self.contexts = []
        self.prediction = prediction if prediction is not None else {
            "choice": "delete", "probabilities": {"archive": 0.3, "delete": 0.7},
        }
        self.error = error

    def predict(self, context):
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return self.prediction


@pytest.fixture
def mail():
    return Message(
        message_id="opaque_mail_id", thread_id="opaque_thread_id", internal_date_ms=1000,
        sender="sender@example.test", recipients=("reader@example.test",),
        subject="A receipt", body_text="Your bicycle repair cost $86.",
        labels=frozenset({"INBOX", "UNREAD"}), attachments=(),
    )


@pytest.fixture
def case(mail):
    return EvaluationCase(
        case_id="SCORER_ONLY_CASE", target_message_id=mail.message_id,
        preferences="Retain receipts.", expected_action="archive", expected_error=None,
        expectation_reason="SCORER_ONLY_REASON", family_id="SCORER_ONLY_FAMILY",
        split="development",
    )


def result(case_id, expected_action, action, *, raw_choice=None, expected_error=None,
           error=None, inference_seconds=1.0):
    return CaseResult(
        case_id=case_id, family_id=f"family_{case_id}", split="development", repetition=1,
        expected_action=expected_action, expected_error=expected_error,
        action=action, raw_choice=raw_choice if raw_choice is not None else action,
        probabilities=None, error=error, token_counts=None, omissions=(), normalizations=(),
        context_seconds=0.01, inference_seconds=inference_seconds, total_seconds=1.01,
    )


def test_runner_never_sends_answer_keys_to_the_predictor(mail, case):
    predictor = RecordingPredictor()
    contradictory_key = replace(case, case_id="ANOTHER_SCORER_CASE", expected_action="delete")
    rows = run_cases([mail], [case, contradictory_key], predictor, repetitions=2)

    assert len(rows) == len(predictor.contexts) == 4
    assert [row.repetition for row in rows] == [1, 1, 2, 2]
    assert [row.action for row in rows] == ["archive"] * 4
    assert [row.raw_choice for row in rows] == ["delete"] * 4
    assert [row.matches_expectation for row in rows] == [True, False, True, False]
    assert len({context.token_ids for context in predictor.contexts}) == 1
    for context in predictor.contexts:
        for secret in (case.case_id, case.family_id, case.expectation_reason,
                       contradictory_key.case_id, mail.message_id, mail.thread_id):
            assert secret not in context.state
        data = json.loads(context.state)
        assert data["user_preferences"] == case.preferences
        assert data["untrusted_mail"]["current"]["body"] == mail.body_text


def test_invalid_input_is_a_reported_error_without_model_inference(mail, case):
    invalid = replace(case, preferences="", expected_action=None,
                      expected_error="invalid_preferences")
    predictor = RecordingPredictor()

    row, = run_cases([mail], [invalid], predictor)

    assert predictor.contexts == []
    assert row.error == "invalid_preferences"
    assert row.action is None
    assert row.raw_choice is None
    assert row.matches_expectation


@pytest.mark.parametrize(("prediction", "failure", "expected_error"), [
    ({"choice": "delete", "probabilities": {"delete": 1}}, None, "invalid_model_output"),
    (None, RuntimeError("PRIVATE EMAIL TEXT"), "inference_failed"),
])
def test_inference_and_validation_failures_never_become_successful_archives(
    mail, case, prediction, failure, expected_error
):
    predictor = RecordingPredictor(prediction=prediction, error=failure)
    row, = run_cases([mail], [case], predictor)

    assert len(predictor.contexts) == 1
    assert row.error == expected_error
    assert row.action is None
    assert not row.matches_expectation
    assert "PRIVATE EMAIL TEXT" not in repr(row)
    assert row.token_counts["total"] > 0
    assert row.context_seconds is not None
    assert row.inference_seconds is not None


def test_failed_first_inference_keeps_its_timing_and_later_inference_is_warm(
    monkeypatch, mail, case
):
    import sweep.decisions.engine as engine

    clock = iter([0, 1, 2, 12, 20, 21, 22, 25])
    monkeypatch.setattr(engine, "perf_counter", lambda: next(clock))

    class FirstCallFails(RecordingPredictor):
        def predict(self, context):
            if not self.contexts:
                self.contexts.append(context)
                raise RuntimeError("Simulated first call failure")
            return super().predict(context)

    rows = run_cases([mail], [case], FirstCallFails(), repetitions=2)

    assert rows[0].error == "inference_failed"
    assert rows[0].inference_seconds == 10
    assert rows[0].context_seconds == 1
    assert rows[1].error is None
    timings = timing_summary(rows)
    assert timings["first_inference_seconds"] == 10
    assert timings["warm_inference_count"] == 1
    assert timings["warm_median_seconds"] == 3


def test_overflow_report_retains_measured_tokens_without_running_the_model(mail, case):
    predictor = RecordingPredictor()
    row, = run_cases([mail], [case], predictor, max_tokens=64)

    assert row.error == "context_overflow"
    assert row.token_counts["total"] > 64
    assert row.context_seconds is not None
    assert row.inference_seconds is None
    assert predictor.contexts == []


def test_metrics_keep_errors_in_denominators_and_distinguish_raw_choices():
    rows = [
        result("a", "delete", "delete"),
        result("b", "archive", "archive", raw_choice="delete"),
        result("c", "delete", "archive", raw_choice="delete"),
        result("d", "archive", "delete"),
        result("e", "delete", None, error="invalid_model_output"),
        result("f", None, None, expected_error="invalid_preferences", error="invalid_preferences"),
        result("g", None, "delete", expected_error="empty_message"),
    ]
    policy, raw = summarize(rows), summarize(rows, raw=True)

    assert policy["action_accuracy"] == {"numerator": 2, "denominator": 5, "value": 0.4}
    assert policy["delete_precision"]["numerator"] == 1
    assert policy["delete_precision"]["denominator"] == 3
    assert policy["delete_recall"]["denominator"] == 3
    assert policy["false_deletes"] == 2
    assert policy["unexpected_errors"] == 1
    assert policy["expected_error_cases"] == 2
    assert policy["expected_errors_matched"] == 1
    assert policy["confusion_matrix"]["delete"] == {"archive": 1, "delete": 1, "error": 1}
    assert raw["delete_precision"]["numerator"] == 2
    assert raw["delete_precision"]["denominator"] == 5
    assert raw["delete_recall"]["numerator"] == 2
    assert raw["false_deletes"] == 3


def test_always_archiving_does_not_get_useful_delete_metrics():
    rows = [result("a", "archive", "archive"), result("b", "delete", "archive")]
    metrics = summarize(rows)

    assert metrics["action_accuracy"]["value"] == 0.5
    assert metrics["delete_precision"] == {"numerator": 0, "denominator": 0, "value": None}
    assert metrics["delete_recall"] == {"numerator": 0, "denominator": 1, "value": 0.0}
    assert summarize([])["action_accuracy"]["value"] is None


def test_repetitions_count_attempts_without_inventing_new_cases():
    row = result("a", "delete", "delete")
    metrics = summarize([row, replace(row, repetition=2)])

    assert metrics["attempts"] == 2
    assert metrics["unique_cases"] == metrics["families"] == 1
    assert metrics["delete_precision"]["denominator"] == 2


def test_timings_exclude_validation_only_rows_and_separate_first_call():
    rows = [
        result("a", None, None, inference_seconds=None,
               expected_error="empty_message", error="empty_message"),
        result("b", "archive", "archive", inference_seconds=10),
        result("c", "archive", "archive", inference_seconds=1),
        result("d", "archive", "archive", inference_seconds=3),
    ]
    timings = timing_summary(rows)

    assert timings["first_inference_seconds"] == 10
    assert timings["warm_inference_count"] == 2
    assert timings["warm_median_seconds"] == 2
    assert timings["warm_p95_seconds"] == 3
    assert timing_summary([])["first_inference_seconds"] is None
    assert timing_summary(rows[:2])["warm_median_seconds"] is None


def test_reports_preserve_raw_policy_and_split_results_without_overwriting(tmp_path):
    rows = [
        result("dev", "archive", "archive", raw_choice="delete"),
        replace(result("held", "delete", "delete"), split="held_out"),
    ]
    metadata = {"split": "all", "delete_threshold": 0.8, "max_tokens": 2048,
                "load_seconds": 0.1, "peak_rss_mib": None}
    output = tmp_path / "report"
    report = write_reports(output, rows, metadata)
    saved_json = (output / "results.json").read_text()

    assert json.loads(saved_json)["raw_model"] == report["raw_model"]
    assert report["policy"]["false_deletes"] == 0
    assert report["raw_model"]["false_deletes"] == 1
    assert set(report["by_split"]) == {"development", "held_out"}
    assert "Incorrect deletes | 0 | 1" in (output / "report.md").read_text()
    assert "raw_choice" in (output / "cases.csv").read_text().splitlines()[0]
    with pytest.raises(FileExistsError):
        write_reports(output, rows, metadata)
    assert (output / "results.json").read_text() == saved_json


def test_reports_show_undefined_precision_instead_of_zero_or_perfect_accuracy(tmp_path):
    metadata = {"split": "development", "delete_threshold": 0.8, "max_tokens": 2048,
                "load_seconds": 0.1, "peak_rss_mib": 512}
    output = tmp_path / "archive-only"
    write_reports(output, [result("a", "delete", "archive")], metadata)

    assert "Delete precision | N/A (0 denominator) | N/A (0 denominator)" in (
        output / "report.md"
    ).read_text()


def test_cli_help_works_outside_the_repository_without_model_setup(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "sweep.evaluation", "--help"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert "--split" in completed.stdout
    assert "--download-model" in completed.stdout


@pytest.mark.parametrize("expected_error", [None, "invalid_preferences"])
def test_cli_defaults_to_development_and_flags_unmatched_expected_errors(
    monkeypatch, tmp_path, message_record, case_record, write_jsonl, expected_error
):
    import sweep.decisions.artifacts as artifacts
    import sweep.decisions.laya as laya
    from sweep.evaluation.__main__ import main

    def forbidden_download(*args, **kwargs):
        raise AssertionError("A default evaluation must not download model files")

    class FakeRuntime(RecordingPredictor):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.metadata = {"test_backend": True}
            self.load_seconds = 0.01

    monkeypatch.setattr(artifacts, "download_model", forbidden_download)
    monkeypatch.setattr(laya, "LayaRuntime", FakeRuntime)
    if expected_error:
        case_record.update(expected_action=None, expected_error=expected_error)
    held_message = {**message_record, "message_id": "held_mail", "thread_id": "held_thread"}
    held_case = {**case_record, "case_id": "held_case", "family_id": "held_family",
                 "target_message_id": "held_mail", "split": "held_out"}
    mail_path = write_jsonl([message_record, held_message], "messages.jsonl")
    case_path = write_jsonl([case_record, held_case], "cases.jsonl")
    output = tmp_path / "cli-report"
    monkeypatch.setattr(sys, "argv", [
        "sweep.evaluation", "--messages", str(mail_path), "--cases", str(case_path),
        "--output", str(output),
    ])

    if expected_error:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
    else:
        main()

    report = json.loads((output / "results.json").read_text())
    assert report["metadata"]["split"] == "development"
    assert report["policy"]["unique_cases"] == 1
    assert report["cases"][0]["case_id"] == case_record["case_id"]
