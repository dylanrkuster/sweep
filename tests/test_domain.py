from dataclasses import FrozenInstanceError, fields

import pytest

from sweep.domain import Attachment, DecisionInput, Message
from sweep.testing.fixtures import load_cases, load_messages
from sweep.testing.mailbox import InMemoryMailbox


def test_messages_own_immutable_collections():
    recipients = ["alex@example.test"]
    labels = ["INBOX", "UNREAD"]
    attachment = Attachment(filename="receipt.pdf", media_type="application/pdf")
    attachments = [attachment]
    message = Message(
        message_id="msg_0001",
        thread_id="thr_0001",
        internal_date_ms=1790064000000,
        sender="sender@example.test",
        recipients=recipients,
        subject="Receipt",
        body_text="Keep this receipt.",
        labels=labels,
        attachments=attachments,
    )

    recipients.append("another@example.test")
    labels.clear()
    attachments.clear()

    assert message.recipients == ("alex@example.test",)
    assert message.labels == frozenset({"INBOX", "UNREAD"})
    assert message.attachments == (attachment,)
    with pytest.raises(FrozenInstanceError):
        message.subject = "Changed"
    with pytest.raises(FrozenInstanceError):
        attachment.filename = "changed.pdf"


def test_decision_input_does_not_share_a_mutable_prior_list(sample_dir):
    messages = load_messages(sample_dir / "messages.jsonl")
    mailbox = InMemoryMailbox(messages)
    prior = list(mailbox.get_prior_thread_messages("msg_0002"))
    decision_input = DecisionInput(
        preferences="Retain receipts.",
        current_message=mailbox.get_message("msg_0002"),
        prior_messages=prior,
    )
    prior.clear()

    assert tuple(message.message_id for message in decision_input.prior_messages) == (
        "msg_0001",
    )
    with pytest.raises(FrozenInstanceError):
        decision_input.preferences = "Changed"


def test_only_runtime_fields_cross_the_decision_boundary(sample_dir):
    messages = load_messages(sample_dir / "messages.jsonl")
    case = load_cases(sample_dir / "cases.jsonl", messages)[0]
    mailbox = InMemoryMailbox(messages)
    decision_input = DecisionInput(
        preferences=case.preferences,
        current_message=mailbox.get_message(case.target_message_id),
        prior_messages=mailbox.get_prior_thread_messages(case.target_message_id),
    )

    assert {field.name for field in fields(decision_input)} == {
        "preferences",
        "current_message",
        "prior_messages",
    }
    annotations = {
        "case_id", "expected_action", "expected_error", "expectation_reason",
        "family_id", "split",
    }
    for runtime_record in (decision_input, decision_input.current_message):
        assert annotations.isdisjoint(field.name for field in fields(runtime_record))
    assert case.expectation_reason not in repr(decision_input)
