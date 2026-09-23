"""Prepare complete evidence and the exact, bounded Laya input sequence.

There is deliberately no semantic evidence selector yet. Section allocations
are starting targets that can borrow unused space; the complete input either
fits or fails. No clipped email is silently treated as a complete decision.
"""

from dataclasses import dataclass
import json
import re
from typing import Protocol, Sequence

from sweep.domain import DecisionInput, Message
from sweep.decisions.question import QUESTION_VERSION, decision_question

CONTEXT_VERSION = "complete-evidence-v1"
DEFAULT_MAX_TOKENS = 2048
MAX_PREFERENCE_CHARACTERS = 1000
STARTING_TOKEN_ALLOCATIONS = {
    "question": 128,
    "preferences": 256,
    "metadata": 64,
    "current_email": 1024,
    "prior_thread": 512,
    "overhead": 64,
}


class Tokenizer(Protocol):
    """The small part of a Hugging Face tokenizer needed before inference."""

    cls_token_id: int
    sep_token_id: int
    mask_token_id: int
    mask_token: str
    all_special_tokens: Sequence[str]

    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]: ...


class ContextError(ValueError):
    """An input cannot produce a complete, valid decision context."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        token_counts: dict[str, int] | None = None,
        omissions: tuple[str, ...] = (),
        normalizations: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.token_counts = dict(token_counts or {})
        self.omissions = omissions
        self.normalizations = normalizations


@dataclass(frozen=True, slots=True)
class PreparedContext:
    state: str
    question: dict[str, object]
    token_ids: tuple[int, ...]
    marker_positions: tuple[int, int]
    token_counts: dict[str, int]
    omissions: tuple[str, ...]
    normalizations: tuple[str, ...]
    max_tokens: int
    question_version: str = QUESTION_VERSION
    context_version: str = CONTEXT_VERSION


def _metadata(message: Message) -> dict[str, object]:
    # Explicit selection keeps mailbox IDs, labels and evaluation annotations out.
    return {
        "sender": message.sender,
        "recipients": list(message.recipients),
        "subject": message.subject,
        "received_at_unix_ms": message.internal_date_ms,
        "attachments": [
            {"filename": item.filename, "media_type": item.media_type}
            for item in message.attachments
        ],
    }


def _mail(message: Message) -> dict[str, object]:
    return {"metadata": _metadata(message), "body": message.body_text}


def _special_spellings(tokenizer: Tokenizer) -> tuple[str, ...]:
    spellings = set(getattr(tokenizer, "all_special_tokens", ()))
    spellings.add(tokenizer.mask_token)
    for name in ("cls_token", "sep_token", "pad_token", "unk_token"):
        spellings.add(getattr(tokenizer, name, None))
    return tuple(sorted((s for s in spellings if s), key=lambda s: (-len(s), s)))


def _serialize(value: object, spellings: tuple[str, ...]) -> tuple[str, bool]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if not spellings:
        return text, False
    pattern = "|".join(re.escape(spelling) for spelling in spellings)

    def escape_first_character(match: re.Match[str]) -> str:
        spelling = match.group(0)
        # JSON decoding reconstructs the original value exactly, while the
        # tokenizer no longer treats email text as a structural special token.
        escaped = json.dumps(spelling[0], ensure_ascii=True)[1:-1]
        if not escaped.startswith("\\"):
            escaped = f"\\u{ord(spelling[0]):04x}"
        return escaped + spelling[1:]

    escaped_text, substitutions = re.subn(pattern, escape_first_character, text)
    return escaped_text, substitutions > 0


def _prior_messages(decision: DecisionInput) -> tuple[tuple[Message, ...], tuple[str, ...]]:
    target = decision.current_message
    eligible: list[Message] = []
    omissions: list[str] = []
    seen: set[Message] = set()
    for index, message in enumerate(decision.prior_messages):
        reason = None
        if message.message_id == target.message_id:
            reason = "current_message"
        elif message.thread_id != target.thread_id:
            reason = "different_thread"
        elif message.internal_date_ms >= target.internal_date_ms:
            reason = "not_strictly_earlier"
        elif message in seen:
            reason = "identical_duplicate"
        if reason:
            omissions.append(f"prior[{index}]:{reason}")
        else:
            seen.add(message)
            eligible.append(message)
    eligible.sort(key=lambda message: (message.internal_date_ms, message.message_id))
    return tuple(eligible), tuple(omissions)


def build_context(
    decision: DecisionInput,
    tokenizer: Tokenizer,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> PreparedContext:
    """Build the SDK's untruncated sequence, with two option score markers.

    Component counts measure each value separately; ``overhead`` is the residual
    for JSON syntax, special tokens and token-boundary differences. ``total`` is
    the exact length sent to the model, not an estimate from character counts.
    """
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    preferences = decision.preferences
    if (
        not isinstance(preferences, str)
        or not preferences.strip()
        or len(preferences) > MAX_PREFERENCE_CHARACTERS
    ):
        raise ContextError("invalid_preferences", "Preferences must contain 1–1000 characters of text.")

    current = decision.current_message
    if not (
        current.subject.strip()
        or current.body_text.strip()
        or any(item.filename.strip() or item.media_type.strip() for item in current.attachments)
    ):
        raise ContextError("empty_message", "The current email has no subject, body or attachment metadata.")

    prior, omissions = _prior_messages(decision)
    spellings = _special_spellings(tokenizer)
    state, escaped_specials = _serialize(
        {
            "user_preferences": preferences,
            "untrusted_mail": {
                "current": _mail(current),
                "earlier_thread": [_mail(message) for message in prior],
            },
        },
        spellings,
    )
    question = decision_question()
    instructions = str(question["instructions"])
    criteria = question["criteria"]
    assert isinstance(criteria, dict)

    def encode(text: str) -> tuple[int, ...]:
        return tuple(tokenizer.encode(text, add_special_tokens=False))

    question_ids = encode("choice question: " + instructions)
    option_ids = tuple(encode(f" {name}: {description}") for name, description in criteria.items())
    question_count = len(question_ids) + sum(len(ids) for ids in option_ids)
    # Pinned SDK common.py format, without its silent option/state truncation.
    tokens = [tokenizer.cls_token_id, *question_ids, tokenizer.sep_token_id]
    markers: list[int] = []
    for option in option_ids:
        markers.append(len(tokens))
        tokens.extend((tokenizer.mask_token_id, *option))
    tokens.extend((tokenizer.sep_token_id, *encode(state), tokenizer.sep_token_id))
    def value_count(value: object) -> int:
        serialized, _ = _serialize(value, spellings)
        return len(encode(serialized))

    counts = {
        "question": question_count,
        "preferences": value_count(preferences),
        "metadata": value_count(_metadata(current)),
        "current_email": value_count(current.body_text),
        "prior_thread": value_count([_mail(message) for message in prior]),
    }
    counts["overhead"] = len(tokens) - sum(counts.values())
    counts["total"] = len(tokens)
    normalizations = ("json_escaped_special_token_spellings",) if escaped_specials else ()
    if question_count > STARTING_TOKEN_ALLOCATIONS["question"] or any(len(ids) > 48 for ids in option_ids):
        raise ContextError(
            "context_overflow",
            "The question exceeds Laya's configured question or option allowance.",
            token_counts=counts,
            omissions=omissions,
            normalizations=normalizations,
        )
    if len(tokens) > max_tokens:
        raise ContextError(
            "context_overflow",
            f"Complete evidence needs {len(tokens)} tokens; the input limit is {max_tokens}. Nothing was truncated.",
            token_counts=counts,
            omissions=omissions,
            normalizations=normalizations,
        )
    return PreparedContext(
        state=state,
        question=question,
        token_ids=tuple(tokens),
        marker_positions=(markers[0], markers[1]),
        token_counts=counts,
        omissions=omissions,
        normalizations=normalizations,
        max_tokens=max_tokens,
    )
