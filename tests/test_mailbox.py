from dataclasses import replace

import pytest

from sweep.testing.fixtures import load_messages
from sweep.testing.mailbox import InMemoryMailbox


def test_prior_thread_lookup_excludes_target_future_and_other_threads(sample_dir):
    messages = load_messages(sample_dir / "messages.jsonl")
    mailbox = InMemoryMailbox(tuple(reversed(messages)))

    assert tuple(
        message.message_id
        for message in mailbox.get_prior_thread_messages("msg_0002")
    ) == ("msg_0001",)
    assert mailbox.get_prior_thread_messages("msg_0001") == ()
    assert mailbox.get_prior_thread_messages("msg_0003") == ()


def test_prior_order_is_deterministic_and_target_time_peers_are_excluded(sample_dir):
    base = load_messages(sample_dir / "messages.jsonl")[0]
    target = replace(base, message_id="msg_0009", internal_date_ms=3000)
    earlier_b = replace(base, message_id="msg_0003", internal_date_ms=2000)
    earlier_a = replace(base, message_id="msg_0002", internal_date_ms=2000)
    first = replace(base, message_id="msg_0001", internal_date_ms=1000)
    same_time = replace(base, message_id="msg_0000", internal_date_ms=3000)
    future = replace(base, message_id="msg_0010", internal_date_ms=4000)
    mailbox = InMemoryMailbox([future, earlier_b, same_time, target, earlier_a, first])

    assert tuple(
        message.message_id
        for message in mailbox.get_prior_thread_messages(target.message_id)
    ) == ("msg_0001", "msg_0002", "msg_0003")


@pytest.mark.parametrize("method", ["get_message", "get_prior_thread_messages"])
def test_unknown_message_id_is_an_explicit_failure(sample_dir, method):
    mailbox = InMemoryMailbox(load_messages(sample_dir / "messages.jsonl"))
    with pytest.raises(KeyError):
        getattr(mailbox, method)("missing")


def test_mailbox_rejects_duplicate_ids(sample_dir):
    message = load_messages(sample_dir / "messages.jsonl")[0]
    with pytest.raises(ValueError):
        InMemoryMailbox([message, replace(message, subject="Conflicting duplicate")])


def test_constructor_input_and_returned_container_cannot_contaminate_reset(sample_dir):
    source = list(load_messages(sample_dir / "messages.jsonl"))
    original = next(message for message in source if message.message_id == "msg_0002")
    mailbox = InMemoryMailbox(source)
    other_mailbox = InMemoryMailbox(source)
    source.clear()
    copied_prior = list(mailbox.get_prior_thread_messages("msg_0002"))
    copied_prior.clear()
    edited_copy = replace(mailbox.get_message("msg_0002"), labels=frozenset())
    mailbox.reset()

    assert edited_copy.labels == frozenset()
    assert mailbox.get_message("msg_0002") == original
    assert other_mailbox.get_message("msg_0002") == original
    assert len(mailbox.get_prior_thread_messages("msg_0002")) == 1
