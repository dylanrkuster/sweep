"""Mailbox facts and decision inputs, independent of Gmail, Laya and test answers.

External adapters validate their input before constructing these typed objects.
Collection fields are copied into immutable containers so callers cannot change
an email by later editing a list they used to construct it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Attachment:
    """Metadata only; Sweep does not read attachment contents."""

    filename: str
    media_type: str


@dataclass(frozen=True, slots=True)
class Message:
    """A normalized email usable by both the fake and eventual Gmail mailbox."""

    message_id: str
    thread_id: str
    internal_date_ms: int
    sender: str
    recipients: tuple[str, ...]
    subject: str
    body_text: str
    labels: frozenset[str]
    attachments: tuple[Attachment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipients", tuple(self.recipients))
        object.__setattr__(self, "labels", frozenset(self.labels))
        object.__setattr__(self, "attachments", tuple(self.attachments))


@dataclass(frozen=True, slots=True)
class DecisionInput:
    """Only information available at decision time; never an evaluation answer.

    This is structured input, not a tokenized prompt. Preference limits,
    evidence selection and token budgeting belong to the future context builder.
    """

    preferences: str
    current_message: Message
    prior_messages: tuple[Message, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "prior_messages", tuple(self.prior_messages))
