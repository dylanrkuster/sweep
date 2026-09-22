"""Validate local fixtures without loading Laya or accessing Gmail."""

import argparse

from sweep.domain import DecisionInput
from sweep.testing.fixtures import FixtureError, load_cases, load_messages
from sweep.testing.mailbox import InMemoryMailbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", required=True, help="Path to synthetic messages.jsonl")
    parser.add_argument("--cases", required=True, help="Path to the separate cases.jsonl answer key")
    args = parser.parse_args()
    try:
        messages = load_messages(args.messages)
        cases = load_cases(args.cases, messages)
    except FixtureError as error:
        parser.error(str(error))

    mailbox = InMemoryMailbox(messages)
    prior_count = 0
    for case in cases:
        # Select runtime fields explicitly; never pass the entire answer record.
        decision_input = DecisionInput(
            preferences=case.preferences,
            current_message=mailbox.get_message(case.target_message_id),
            prior_messages=mailbox.get_prior_thread_messages(case.target_message_id),
        )
        prior_count += len(decision_input.prior_messages)

    print(f"Validated {len(messages)} messages and {len(cases)} cases.")
    print(f"Assembled {len(cases)} decision inputs with {prior_count} prior-message references.")
    print("Fixture check only: no model predictions or mailbox changes.")


if __name__ == "__main__":
    main()
