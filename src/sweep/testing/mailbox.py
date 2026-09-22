"""The read-only starting point for Sweep's reusable fake mailbox."""

from collections.abc import Iterable
from typing import Protocol

from sweep.domain import Message


class MailboxReader(Protocol):
    """The lookup operations shared by fake and future real mailbox adapters."""

    def get_message(self, message_id: str) -> Message: ...

    def get_prior_thread_messages(self, message_id: str) -> tuple[Message, ...]: ...


class InMemoryMailbox:
    """Independent mailbox state backed by immutable normalized messages.

    There are no label mutations yet. Reset preserves the initial snapshot for
    the later job-testing adapter; immutable results can safely be shared.
    """

    def __init__(self, messages: Iterable[Message]) -> None:
        self._initial_messages = tuple(messages)
        ids = [message.message_id for message in self._initial_messages]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate message_id in mailbox")
        self.reset()

    def reset(self) -> None:
        self._messages = {message.message_id: message for message in self._initial_messages}

    def get_message(self, message_id: str) -> Message:
        return self._messages[message_id]

    def get_prior_thread_messages(self, message_id: str) -> tuple[Message, ...]:
        target = self.get_message(message_id)
        earlier = (
            message
            for message in self._messages.values()
            if message.thread_id == target.thread_id
            and message.internal_date_ms < target.internal_date_ms
        )
        # IDs make the order of earlier timestamp ties repeatable; they do not
        # establish chronology for peers sharing the target's own timestamp.
        return tuple(sorted(earlier, key=lambda message: (message.internal_date_ms, message.message_id)))
