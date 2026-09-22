"""Small synthetic records for testing the fixture boundary itself."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def message_record():
    return {
        "schema_version": 1,
        "message_id": "msg_0001",
        "thread_id": "thr_0001",
        "internal_date_ms": 1790064000000,
        "sender": "sender@example.test",
        "recipients": ["alex@example.test"],
        "subject": "An example message",
        "body_text": "Synthetic mail for a fixture validation test.",
        "labels": ["INBOX", "UNREAD"],
        "attachments": [],
    }


@pytest.fixture
def case_record():
    return {
        "schema_version": 1,
        "case_id": "case_0001",
        "target_message_id": "msg_0001",
        "preferences": "Retain messages that could matter later.",
        "expected_action": "archive",
        "expected_error": None,
        "expectation_reason": "This is a synthetic expected answer.",
        "family_id": "family_0001",
        "split": "development",
    }


@pytest.fixture
def write_jsonl(tmp_path):
    def write(records, filename="records.jsonl"):
        path = tmp_path / filename
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
        return path

    return write


@pytest.fixture
def sample_dir():
    return Path(__file__).parent / "fixtures"
