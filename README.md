# Sweep

Handle my inbox the way I would.

Sweep is an open-source Gmail add-on for clearing unread email with one button.

Set your preferences, choose how many unread emails to sweep, and press **Sweep**. The MVP processes messages from newest to oldest, one at a time. Laya English makes one decision per email: **archive** or **move to Trash**. Successfully processed messages are marked read, and Sweep saves a summary of the results.

Delete means Gmail's recoverable Trash behavior; Sweep does not permanently delete messages. Gmail ordinarily removes trashed mail after 30 days.

## Project status

MVP scope finalized September 22, 2026. Implementation has not started; no application, mailbox connection or model evaluation has been completed.

- Native Gmail Google Workspace add-on.
- Python API and background worker hosted on Modal.
- Google Firestore for preferences, job state and saved results.
- Laya English with an initial 2,048-token decision context.
- Initial hosting target: recurring free allowances, subject to measured usage.

The first implementation milestone is a standalone evaluator using synthetic emails to check decisions, memory use and latency. Custom labels, billing and enterprise features are later work.

## License

Sweep's application code uses the [MIT License](LICENSE). Model weights and dependencies retain their respective licenses. A paid managed service may be offered separately.
