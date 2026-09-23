"""Keep the checked-in evaluation data usable and its split boundaries intact."""

from collections import Counter, defaultdict
from pathlib import Path

import pytest

from sweep.testing.fixtures import load_cases, load_messages
from sweep.testing.mailbox import InMemoryMailbox


@pytest.fixture(scope="module")
def corpus():
    directory = Path(__file__).parent / "fixtures" / "evaluation"
    messages = load_messages(directory / "messages.jsonl")
    return messages, load_cases(directory / "cases.jsonl", messages)


def test_corpus_covers_both_actions_and_explicit_validation_failures(corpus):
    messages, cases = corpus

    assert len(messages) == 43
    assert len(cases) == 40
    assert Counter(case.split for case in cases) == {"development": 26, "held_out": 14}
    assert Counter(case.expected_action or case.expected_error for case in cases) == {
        "archive": 18,
        "delete": 14,
        "invalid_preferences": 3,
        "empty_message": 2,
        "context_overflow": 3,
    }
    for split in ("development", "held_out"):
        assert {case.expected_action for case in cases if case.split == split} == {
            "archive", "delete", None,
        }


def test_corpus_uses_fictional_addresses_and_keeps_related_mail_in_one_split(corpus):
    messages, cases = corpus
    by_id = {message.message_id: message for message in messages}
    boundaries = defaultdict(set)

    for message in messages:
        assert message.sender.endswith(".test")
        assert all(recipient.endswith(".test") for recipient in message.recipients)

    for case in cases:
        message = by_id[case.target_message_id]
        boundaries[("family", case.family_id)].add(case.split)
        boundaries[("thread", message.thread_id)].add(case.split)
        # Also catch copied nonempty mail assigned new IDs and families.
        content = (message.subject.strip(), message.body_text.strip())
        if any(content):
            boundaries[("content", content)].add(case.split)

    assert all(len(splits) == 1 for splits in boundaries.values())


def test_corpus_has_preference_reversals_without_crossing_splits(corpus):
    _, cases = corpus
    by_target = defaultdict(list)
    for case in cases:
        by_target[case.target_message_id].append(case)

    reversals = [
        variants for variants in by_target.values()
        if {case.expected_action for case in variants} == {"archive", "delete"}
    ]
    assert reversals
    for variants in reversals:
        assert len({case.preferences for case in variants}) == len(variants)
        assert len({case.family_id for case in variants}) == 1
        assert len({case.split for case in variants}) == 1


def test_thread_cases_have_earlier_evidence_and_a_future_reply_is_excluded(corpus):
    messages, cases = corpus
    mailbox = InMemoryMailbox(messages)
    with_context = [
        case for case in cases
        if mailbox.get_prior_thread_messages(case.target_message_id)
    ]
    assert len(with_context) >= 3
    assert {case.split for case in with_context} == {"development", "held_out"}

    targets_with_future_reply = []
    for case in with_context:
        current = mailbox.get_message(case.target_message_id)
        future = [
            message for message in messages
            if message.thread_id == current.thread_id
            and message.internal_date_ms > current.internal_date_ms
        ]
        if future:
            targets_with_future_reply.append(current.message_id)
            assert not set(future).intersection(
                mailbox.get_prior_thread_messages(current.message_id)
            )
    assert targets_with_future_reply


def test_oversized_variants_remain_development_error_cases(corpus):
    messages, cases = corpus
    by_id = {message.message_id: message for message in messages}
    oversized = [case for case in cases if case.expected_error == "context_overflow"]

    assert len({case.family_id for case in oversized}) == 1
    assert {case.split for case in oversized} == {"development"}
    assert all(
        len(by_id[case.target_message_id].body_text.split()) > 5000
        for case in oversized
    )
