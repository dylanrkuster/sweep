import json
from dataclasses import replace

import pytest

from sweep.testing.fixtures import FixtureError, load_cases, load_messages


def assert_line_error(error, path, line):
    assert f"{path}:{line}:" in str(error.value)


def test_seed_fixtures_load_as_separate_mail_and_expected_answers(sample_dir):
    messages = load_messages(sample_dir / "messages.jsonl")
    cases = load_cases(sample_dir / "cases.jsonl", messages)

    assert len(messages) == 5
    assert len(cases) == 3
    assert {case.expected_action for case in cases} == {"archive", "delete"}
    assert len({case.family_id for case in cases}) >= 2
    assert {case.split for case in cases} == {"development"}
    assert all(message.sender.endswith(".test") for message in messages)
    assert all(
        recipient.endswith(".test")
        for message in messages
        for recipient in message.recipients
    )


@pytest.mark.parametrize("contents", ["", "\n  \n"])
def test_empty_mail_dataset_is_rejected(tmp_path, contents):
    path = tmp_path / "empty.jsonl"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert str(path) in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("internal_date_ms", True),
        ("internal_date_ms", -1),
        ("internal_date_ms", "1790064000000"),
        ("recipients", "alex@example.test"),
        ("attachments", [{"filename": "receipt.pdf"}]),
        ("labels", ["UNREAD", 42]),
        ("message_id", ""),
        ("sender", None),
    ],
)
def test_invalid_mail_fields_are_rejected(message_record, write_jsonl, field, value):
    message_record[field] = value
    path = write_jsonl([message_record])
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert_line_error(error, path, 1)


@pytest.mark.parametrize("change", ["missing", "annotation", "attachment_annotation"])
def test_mail_schema_prevents_annotations_and_missing_fields(
    message_record, write_jsonl, change
):
    if change == "missing":
        del message_record["body_text"]
    elif change == "annotation":
        message_record["expected_action"] = "archive"
    else:
        message_record["attachments"] = [
            {"filename": "receipt.pdf", "media_type": "application/pdf", "answer": "archive"}
        ]
    path = write_jsonl([message_record])
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert_line_error(error, path, 1)


def test_duplicate_message_id_reports_the_conflicting_line(message_record, write_jsonl):
    path = write_jsonl([message_record, {**message_record, "subject": "A different body"}])
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert_line_error(error, path, 2)


def test_malformed_json_reports_original_file_and_line(message_record, tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text(json.dumps(message_record) + "\n{broken}\n", encoding="utf-8")
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert_line_error(error, path, 2)


def test_duplicate_json_keys_are_not_silently_overwritten(message_record, tmp_path):
    path = tmp_path / "ambiguous.jsonl"
    encoded = json.dumps(message_record)
    path.write_text(encoded[:-1] + ', "message_id": "msg_0002"}\n', encoding="utf-8")
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert_line_error(error, path, 1)


def test_invalid_data_diagnostics_do_not_echo_message_values(message_record, write_jsonl):
    marker = "PRIVATE-SYNTHETIC-CONTENT-DO-NOT-ECHO"
    message_record["body_text"] = {marker: marker}
    path = write_jsonl([message_record])
    with pytest.raises(FixtureError) as error:
        load_messages(path)
    assert marker not in str(error.value)
    assert_line_error(error, path, 1)


def test_empty_or_oversized_content_remains_available_for_decision_validation(
    message_record, case_record, write_jsonl
):
    message_record.update(subject="", body_text="")
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    case_record["preferences"] = "x" * 1001
    cases = load_cases(write_jsonl([case_record], "cases.jsonl"), messages)

    assert messages[0].body_text == ""
    assert messages[0].subject == ""
    assert len(cases[0].preferences) == 1001


def test_empty_case_dataset_is_rejected(message_record, write_jsonl):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    path = write_jsonl([], "cases.jsonl")
    with pytest.raises(FixtureError) as error:
        load_cases(path, messages)
    assert str(path) in str(error.value)


@pytest.mark.parametrize(
    ("patch", "remove"),
    [
        ({"expected_error": "invalid_input"}, None),
        ({"expected_action": None}, None),
        ({"expected_action": "keep"}, None),
        ({"expected_action": None, "expected_error": ""}, None),
        ({"target_message_id": "missing"}, None),
        ({"schema_version": True}, None),
        ({"split": "mystery"}, None),
        ({"unexpected_field": "value"}, None),
        ({}, "expected_action"),
    ],
)
def test_invalid_cases_are_rejected(
    message_record, case_record, write_jsonl, patch, remove
):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    case_record.update(patch)
    if remove:
        del case_record[remove]
    path = write_jsonl([case_record], "cases.jsonl")
    with pytest.raises(FixtureError) as error:
        load_cases(path, messages)
    assert_line_error(error, path, 1)


def test_expected_error_is_not_replaced_with_archive(message_record, case_record, write_jsonl):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    case_record.update(expected_action=None, expected_error="invalid_input", preferences="")
    cases = load_cases(write_jsonl([case_record], "cases.jsonl"), messages)
    assert cases[0].expected_action is None
    assert cases[0].expected_error == "invalid_input"
    assert cases[0].preferences == ""


def test_duplicate_case_ids_are_rejected(message_record, case_record, write_jsonl):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    path = write_jsonl([case_record, case_record], "cases.jsonl")
    with pytest.raises(FixtureError) as error:
        load_cases(path, messages)
    assert_line_error(error, path, 2)


def test_cases_reject_duplicate_json_keys(message_record, case_record, write_jsonl, tmp_path):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    path = tmp_path / "cases.jsonl"
    encoded = json.dumps(case_record)
    path.write_text(encoded[:-1] + ', "expected_action": "delete"}\n', encoding="utf-8")
    with pytest.raises(FixtureError) as error:
        load_cases(path, messages)
    assert_line_error(error, path, 1)


@pytest.mark.parametrize("shared", ["family", "thread"])
def test_related_cases_cannot_cross_dataset_splits(
    message_record, case_record, write_jsonl, shared
):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    another_message = replace(
        messages[0],
        message_id="msg_0002",
        thread_id="thr_0002" if shared == "family" else messages[0].thread_id,
    )
    messages = (*messages, another_message)
    another_case = {
        **case_record,
        "case_id": "case_0002",
        "target_message_id": "msg_0002",
        "family_id": case_record["family_id"] if shared == "family" else "family_0002",
        "split": "held_out",
    }
    path = write_jsonl([case_record, another_case], "cases.jsonl")
    with pytest.raises(FixtureError) as error:
        load_cases(path, messages)
    assert_line_error(error, path, 2)


def test_one_message_can_have_multiple_preference_cases(
    message_record, case_record, write_jsonl
):
    messages = load_messages(write_jsonl([message_record], "messages.jsonl"))
    second_case = {
        **case_record,
        "case_id": "case_0002",
        "preferences": "Discard this kind of message.",
        "expected_action": "delete",
    }
    cases = load_cases(write_jsonl([case_record, second_case], "cases.jsonl"), messages)
    assert cases[0].target_message_id == cases[1].target_message_id
    assert cases[0].expected_action != cases[1].expected_action
