"""Strict JSONL loading, with evaluation answers kept outside mailbox objects."""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sweep.domain import Attachment, Message


class FixtureError(ValueError):
    """An invalid fixture, identified by file and line without dumping mail text."""


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """Answer-key data for the scorer, never the model's input schema."""

    case_id: str
    target_message_id: str
    preferences: str
    expected_action: Literal["archive", "delete"] | None
    expected_error: str | None
    expectation_reason: str
    family_id: str
    split: Literal["development", "held_out"]


MESSAGE_FIELDS = {
    "schema_version", "message_id", "thread_id", "internal_date_ms", "sender",
    "recipients", "subject", "body_text", "labels", "attachments",
}
CASE_FIELDS = {
    "schema_version", "case_id", "target_message_id", "preferences",
    "expected_action", "expected_error", "expectation_reason", "family_id", "split",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _records(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    found = False
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                found = True
                try:
                    record = json.loads(
                        line, object_pairs_hook=_unique_object, parse_constant=_reject_constant
                    )
                except ValueError as error:
                    # JSON decoder messages can contain source values. Keep
                    # diagnostics useful without printing the offending email.
                    raise FixtureError(f"{path}:{line_number}: invalid JSON record ({type(error).__name__})") from None
                if not isinstance(record, dict):
                    raise FixtureError(f"{path}:{line_number}: record must be a JSON object")
                yield line_number, record
    except (OSError, UnicodeError) as error:
        raise FixtureError(f"{path}: cannot read UTF-8 fixture ({type(error).__name__})") from None
    if not found:
        raise FixtureError(f"{path}: fixture contains no records")


def _fields(record: Any, expected: set[str]) -> None:
    if not isinstance(record, dict):
        raise ValueError("expected a JSON object")
    if set(record) != expected:
        # Don't echo unknown field names: they could themselves contain mail.
        raise ValueError("record has missing or unknown fields")


def _version(record: dict[str, Any]) -> None:
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{field} must be {'a' if allow_empty else 'a nonempty'} string")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array of strings")
    return tuple(_text(item, field) for item in value)


def _message(record: dict[str, Any]) -> Message:
    _fields(record, MESSAGE_FIELDS)
    _version(record)
    timestamp = record["internal_date_ms"]
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("internal_date_ms must be a nonnegative integer")
    if not isinstance(record["attachments"], list):
        raise ValueError("attachments must be an array")
    attachments = []
    for item in record["attachments"]:
        _fields(item, {"filename", "media_type"})
        attachments.append(Attachment(
            filename=_text(item["filename"], "filename", allow_empty=True),
            media_type=_text(item["media_type"], "media_type"),
        ))
    return Message(
        message_id=_text(record["message_id"], "message_id"),
        thread_id=_text(record["thread_id"], "thread_id"),
        internal_date_ms=timestamp,
        sender=_text(record["sender"], "sender", allow_empty=True),
        recipients=_strings(record["recipients"], "recipients"),
        subject=_text(record["subject"], "subject", allow_empty=True),
        body_text=_text(record["body_text"], "body_text", allow_empty=True),
        labels=frozenset(_strings(record["labels"], "labels")),
        attachments=tuple(attachments),
    )


def load_messages(path: str | Path) -> tuple[Message, ...]:
    """Load mailbox facts only, rejecting answer annotations and duplicate IDs."""
    path = Path(path)
    messages: dict[str, Message] = {}
    for line, record in _records(path):
        try:
            message = _message(record)
            if message.message_id in messages:
                raise ValueError("duplicate message_id")
        except ValueError as error:
            raise FixtureError(f"{path}:{line}: {error}") from None
        messages[message.message_id] = message
    return tuple(messages.values())


def _case(record: dict[str, Any]) -> EvaluationCase:
    _fields(record, CASE_FIELDS)
    _version(record)
    action, error = record["expected_action"], record["expected_error"]
    if action is not None and action not in ("archive", "delete"):
        raise ValueError("expected_action must be archive, delete or null")
    if error is not None:
        _text(error, "expected_error")
    if (action is None) == (error is None):
        raise ValueError("exactly one of expected_action and expected_error must be set")
    split = record["split"]
    if split not in ("development", "held_out"):
        raise ValueError("split must be development or held_out")
    return EvaluationCase(
        case_id=_text(record["case_id"], "case_id"),
        target_message_id=_text(record["target_message_id"], "target_message_id"),
        preferences=_text(record["preferences"], "preferences", allow_empty=True),
        expected_action=action,
        expected_error=error,
        expectation_reason=_text(record["expectation_reason"], "expectation_reason"),
        family_id=_text(record["family_id"], "family_id"),
        split=split,
    )


def load_cases(path: str | Path, messages: Iterable[Message]) -> tuple[EvaluationCase, ...]:
    """Validate the separate answer key, references and dataset split boundaries.

    Related cases must share a split, both by declared family and by actual
    thread. This prevents alternate preferences for the same mail leaking
    between development and held-out evaluation even under different families.
    """
    path = Path(path)
    message_list = tuple(messages)
    by_id = {message.message_id: message for message in message_list}
    if len(by_id) != len(message_list):
        raise FixtureError(f"{path}: duplicate message_id in supplied messages")
    cases: dict[str, EvaluationCase] = {}
    family_splits: dict[str, str] = {}
    thread_splits: dict[str, str] = {}
    for line, record in _records(path):
        try:
            case = _case(record)
            if case.case_id in cases:
                raise ValueError("duplicate case_id")
            if case.target_message_id not in by_id:
                raise ValueError("target_message_id does not reference a loaded message")
            thread = by_id[case.target_message_id].thread_id
            if family_splits.get(case.family_id, case.split) != case.split:
                raise ValueError("family_id crosses dataset splits")
            if thread_splits.get(thread, case.split) != case.split:
                raise ValueError("message thread crosses dataset splits")
        except ValueError as error:
            raise FixtureError(f"{path}:{line}: {error}") from None
        cases[case.case_id] = case
        family_splits[case.family_id] = case.split
        thread_splits[thread] = case.split
    return tuple(cases.values())
