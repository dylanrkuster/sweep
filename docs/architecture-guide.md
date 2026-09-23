# Architecture details

**Design status:** Modal plus Firestore is the selected stack. This document describes the intended implementation; the application and its resource measurements are not complete.

[Architecture map](architecture.md) · [Product scope](product.md) · [Database](database.md) · [Evaluator plan](evaluator-plan.md)

## Start with a familiar web application

The core is a familiar pattern: **interface → REST API → database**. Gmail supplies the interface; our Python API accepts requests; Firestore saves the records.

Processing many emails can take longer than a button request should wait. The API therefore creates a **job**, a saved instruction such as “process up to 50 unread emails with these preferences,” and hands it to a **background worker**, the Python code that carries out that instruction. Modal's execution system queues the submitted function call until it can run.

A job is data, not a server. The worker is a program, not a separate website. The API and worker can import shared Python modules while running in separate processes. This lets the button respond promptly and lets the work continue after Gmail closes.

## Where the components live

| Component | Location | What it is |
| --- | --- | --- |
| Gmail interface | Google's Gmail client | Native controls rendered from JSON returned by our API. |
| Add-on registration | A Google Cloud project | A manifest describing callbacks and permissions. |
| Python API | Modal Server | A small Python process that handles HTTPS requests. |
| Dispatch and selection | Modal Functions | Short-lived Python code that freezes selected message IDs and starts the worker. |
| Worker and Laya | Modal Function | Python code that processes one email at a time, with the model loaded in memory. |
| Model files | Modal Volume | Persistent weights and tokenizer files for an exact model revision. |
| Saved records | Google Firestore | A managed document database for preferences, jobs, credentials and outcomes. |
| Runtime secrets | Modal Secrets | Private keys and configuration supplied only to authorized processes. |
| Mailbox | Gmail | The user's actual messages, accessed through the Gmail API. |
| Recovery and cleanup | Scheduled Modal Functions | Timer-triggered Python functions that repair interrupted work and remove eligible old records. |

A Google Cloud project groups configuration, permissions and services. It does not by itself rent a computer. Firestore runs independently of our Modal processes, so replacing a worker does not erase its saved progress.

## The interface and API

Our code describes Gmail cards using **JSON**, the structured-data format common in REST APIs. It asks Google to render preferences, an email count, a Sweep button and saved counts. It does not inject JavaScript into Gmail or require a Chrome extension. Google's HTTP add-on support lets an ordinary HTTPS backend return these cards. [Google's add-on guide](https://developers.google.com/workspace/add-ons/guides/alternate-runtimes)

**FastAPI** maps a URL and HTTP method to a Python function. **Uvicorn** is the server program that listens for requests and runs that function. For example, a proposed `POST /addon/sweep` route validates the submitted count and starts a job; `/addon/result` reads the saved result. Multiple routes can run in the same server process.

Modal starts that process inside a **container**: Python, our files and their dependencies packaged together. An **image** is the stored package used to create the container. Modal supplies the HTTPS address and forwards requests to Uvicorn. Only our API routes answer those requests; publishing MIT source does not expose production secrets or the deployed filesystem.

The API should stay small and avoid importing the machine-learning libraries. One ready instance is the initial design because Modal Servers can return HTTP 503 when no container is ready. The heavier model worker can stop when idle. The API's candidate CPU and memory allocation still needs measurement. [Modal Servers](https://modal.com/docs/guide/servers)

The Server interface also avoids storing request/response payloads in Modal's execution records, unlike ordinary Function arguments and results, which may be retained. Queued calls therefore carry only a job ID, and our own logs must exclude OAuth codes, tokens and mail content. [Modal data retention](https://modal.com/docs/guide/security)

## Connecting an account

We must verify both **who is using Sweep** and **which mailbox Sweep may access**. Google's signed identity information authenticates the caller. Gmail authorization supplies permission to read and modify that person's messages.

An **access token** is a short-lived pass for Gmail requests. A **refresh token** lets the backend obtain replacement access tokens so a job can continue after the button callback ends. The connection flow must explicitly request the required offline access; the add-on callback is not a permanent credential. [Google's server authorization guide](https://developers.google.com/identity/protocols/oauth2/web-server)

Refresh tokens are encrypted before storage in Firestore; the encryption key lives in Modal Secrets. The authorization callback uses an expiring, single-use state record and verifies that the granting Google account matches the initiating user. Required permissions are checked even after consent. Revoked or incomplete access stops further mailbox work and requires reconnection.

## Follow one sweep from click to result

1. **Accept the request.** Google calls our API with the form values and authenticated event. The API verifies identity, permission, count, preferences and available capacity.
2. **Save the job.** A Firestore transaction creates the job, sets the account's active-job pointer and consumes the submission token together. A transaction means these database changes succeed together or none applies. A repeated click with the same submission returns the existing job.
3. **Record and dispatch the work.** The job includes a saved dispatch intention: “this still needs a controller.” The API then submits the job ID to Modal and returns a card. If it crashes between saving and dispatching, recovery can find that saved intention.
4. **Freeze the selection.** The controller discovers up to N eligible unread messages outside Spam, Trash and Drafts. It sorts by Gmail's internal timestamp with a deterministic tie-breaker, then saves a fixed ordered list of distinct IDs. An empty selection completes without loading Laya.
5. **Start the worker.** The worker claims a temporary job lease and loads the pinned model files. It processes the first unresolved item, then each subsequent item sequentially.
6. **Evaluate one message.** Recheck eligibility, fetch the email and useful prior thread context, construct the budgeted input and call Laya directly in Python. The model has two outcomes: Archive or Delete. Policy code validates the result before any mailbox mutation.
7. **Save the intended action.** Record the exact label change and relevant previous mailbox state before sending the request to Gmail.
8. **Confirm and checkpoint.** Confirm the required mailbox state, then save the item outcome, update counts and advance the cursor in one database transaction. Only then attempt the next message.
9. **Finish and display.** When no operation remains uncertain, save the summary and release the account lock. The results action or reopening the add-on reads those saved counts; it does not run Laya again.

Gmail's list API does not document a newest-first ordering guarantee. Examining only the first N results and sorting them is insufficient to prove they are the newest N. Selection may inspect many more messages, so discovery over large unread backlogs is a distinct benchmark and needs a bounded, correct algorithm. [List API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)

An unattempted message that became read or otherwise ineligible is skipped without mutation. An item with an earlier uncertain write must instead be reconciled: our own request may explain its changed labels. Context from other thread messages never grants permission to change those messages.

## What Archive and Delete actually send

Archive removes `INBOX` and `UNREAD` labels. The preferred Delete request adds `TRASH` and removes `INBOX` and `UNREAD`. Unrelated labels should be preserved. A controlled-mailbox test must confirm the combined operation's exact behavior. Sweep never calls `messages.delete` or empties Trash. [Gmail labels](https://developers.google.com/workspace/gmail/api/guides/labels), [message modification](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify)

If integration requires a dedicated Trash call followed by a separate mark-read call, each step must be saved and confirmed independently. Success is counted only after both finish. A failure between the calls leaves the current message partially changed, not untouched or successfully processed.

## The model is inside the worker

The worker loads Laya English from a persistent Volume into RAM and makes an **in-process call**—a Python function call inside the same program. There is no separate model API or extra network hop. The on-disk files survive shutdown; their in-memory copy disappears, so a later worker may spend time loading the model again.

The agreed input budget is:

| Input | Tokens |
| --- | ---: |
| Question and options | 128 |
| User preferences | 256 |
| Message metadata | 64 |
| Current email and prior thread | 1,536 |
| Formatting/tokenizer overhead | 64 |
| **Total** | **2,048** |

Content starts at 1,024 current-email tokens and 512 thread tokens; unused space can move between them. A tokenizer converts text into the model's tokens. Character count is not token count, so the evaluator must measure the actual packed input and prevent silent truncation.

The proposed policy prefers Archive when a valid evaluation lacks sufficient evidence for Delete. Thresholds need evaluation; Laya's raw score is not assumed calibrated. An inference or input-preparation failure stops the item before mutation instead of silently becoming Archive. Email text is input data, never authority to execute commands or expand the permitted actions. Attachment contents are not interpreted in this MVP.

## Recovery is part of the normal design

A **lease** is a temporary claim by one controller or worker. Its increasing generation number prevents an older invocation from overwriting newer database results. Both discovery and processing need this protection because a platform can deliver work more than once.

Lease expiry alone does not prove the old process or its Gmail request stopped. Recovery must establish termination, account for bounded request deadlines and reconcile outstanding writes before permitting another mutation. Gmail does not understand our lease number and cannot reject stale requests for us.

A timeout means no timely response arrived, not that Gmail rejected the change. The worker rereads mailbox state and compares it with the saved intention. If evidence remains ambiguous, the job retains an unresolved outcome. It does not invent success or describe the message as untouched. Later selected items remain unattempted.

Firestore and Gmail cannot share one transaction. Database transactions protect our counters and checkpoints; they do not guarantee external requests happen exactly once. Their callbacks may rerun, so Gmail calls must stay outside them. [Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions)

## Privacy, cost and build order

Firestore stores references, preferences, encrypted credentials, decisions and recovery records, not a second mailbox. Raw bodies, copied attachments, full prompts and tokens must not enter logs or permanent application storage. Public fixtures are synthetic; production records remain private regardless of the source license.

The initial Firestore project uses Spark without billing. Work admission must leave capacity for checkpoints and recovery before approaching free quotas. Our reservation records estimate capacity; they are not a block of resources guaranteed by the provider. A database outage or exhausted quota can delay saving or displaying a final result. [Firestore quotas](https://firebase.google.com/docs/firestore/quotas)

Modal worker CPU, memory, startup delay and sustainable usage remain measurements to make, not proven capacity. Begin with the [local evaluator and reusable fake-mail environment](evaluator-plan.md), then build the sequential job engine, benchmark Modal, add durable records, and connect Gmail. Subscription billing and enterprise deployment are deferred. The [database guide](database.md) explains the records that make this design recoverable.
