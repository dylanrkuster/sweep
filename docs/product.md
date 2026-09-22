# Product scope

Sweep is an MIT-licensed, open-source Gmail add-on that processes a requested number of unread emails according to the user's preferences. The MVP is defined; application implementation and hosting measurements are still ahead.

[README](../README.md) · [Architecture](architecture.md) · [Database](database.md) · [Evaluator plan](evaluator-plan.md)

## The MVP

The native Gmail panel has three inputs: saved free-text preferences, a number of emails to process, and a **Sweep** button. Preferences initially allow up to 1,000 characters, subject to validation against the model's token budget.

Sweep selects up to the requested number of unread individual messages, newest first, and processes them one at a time. Laya English makes one decision per email:

| Decision | Required final state |
| --- | --- |
| **Archive** | Retain the message, remove it from the Inbox if present, and mark it read. |
| **Delete** | Move the message to Gmail Trash and mark it read. Never permanently delete it. |

Gmail ordinarily removes messages from Trash after 30 days. Sweep does not empty Trash or call Gmail's permanent-delete endpoint. A successful archive retains a message even when it needs attention; the MVP has no keep-in-Inbox outcome or custom labels. [Gmail deletion behavior](https://support.google.com/mail/answer/7401?hl=en)

The saved result is a short summary, such as “37 archived, 13 moved to Trash. All 50 marked read.” It is retrieved through a results action or by reopening the add-on. Live progress and a separate results dashboard are unnecessary.

## Processing rules

- One active sweep per account. Repeated delivery of the same start request returns the same job.
- Freeze a distinct, ordered selection before model processing. Do not assume Gmail's list endpoint guarantees newest-first order.
- Recheck eligibility immediately before processing each message. If it has already become read or otherwise ineligible, record a skip without changing it.
- Fetching thread context does not authorize changing the other messages in that thread.
- Save the intended mailbox change before sending it. Count success only after the action and read status are confirmed.
- A permanent processing failure stops the job, preserves confirmed successes, and leaves later messages unattempted. A timed-out write may already have changed Gmail; reconcile it before describing that message as untouched.
- Closing Gmail does not cancel accepted background work.
- A fresh sweep checks currently unread mail again. Previously processed mail can be selected again if it later becomes unread.
- If fewer than the requested number exist, process those available. If none exist, complete after checking Gmail without loading Laya.

## Starting implementation defaults

Eligible mail is all unread individual messages outside Spam, Trash and Drafts, including already archived unread mail. We will verify the query and final label checks during integration. A small configurable maximum sweep size and measured global limits control initial operating costs.

The decision policy should prefer Archive when a valid evaluation does not provide sufficient evidence for Delete. The threshold needs calibration on examples; a model score is not assumed to be a reliable probability. Invalid output, failed inference or insufficient required input is an execution failure, not a third successful action or an excuse to mark the message read.

The MVP does not download or interpret attachments. It includes their presence in the context and conservatively retains messages whose unseen attachments could matter. These extraction and decision rules will be versioned and evaluated.

The initial context is **2,048 tokens**: 128 for the question/options, 256 for preferences, 64 for metadata, 1,536 for email/thread content, and 64 for formatting/tokenizer overhead. The content allocation starts at 1,024 current-email tokens plus 512 prior-thread tokens, with unused space transferable between them. The actual tokenizer must enforce the total without silent truncation.

## Hosting, privacy and licensing

Modal runs the Python API and background workers, stores model files on a Volume, and supplies application Secrets. Google's Firestore stores durable application records. Initial operation must fit entirely inside recurring free allowances; capacity and resource sizes remain unmeasured. Trial credits and a small recurring charge do not satisfy that target.

Open-source code does not make production data public. Credentials stay private, refresh tokens are encrypted, and raw emails do not enter application logs, queued arguments or permanent application storage. Public test messages must be synthetic. Sweep's [MIT license](../LICENSE) does not replace the licenses of Laya or other dependencies.

## Deferred work

Custom categories, additional model decisions, recurring automatic sweeps, live progress, attachment interpretation, permanent deletion, subscriptions, team administration and enterprise customization are outside the first working release. Paid managed hosting remains a possible business model; its pricing and features are undecided.

The first milestone is a [standalone Laya evaluator](evaluator-plan.md) with reusable synthetic messages. It establishes decision quality, context handling and local resource measurements before connecting a real mailbox.
