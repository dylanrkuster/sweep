# Building the standalone Laya evaluator

**Status: implementation plan.** The evaluator, fixtures and commands described below have not been implemented. This is the first build milestone for [Sweep's MVP](product.md). It needs no Gmail account or cloud deployment.

The milestone has two outputs: a reusable way to represent test emails, and a program that evaluates Laya's archive/delete decisions against expected answers. The same input format and context-building code will later feed the real sweep worker. Model scores do not directly execute mailbox changes.

## 1. Set up a small Python package

Start with Python 3.11 in an isolated environment and a dependency lockfile. An isolated environment keeps Sweep's libraries separate from the computer's other Python projects. A lockfile records exact versions so another developer can reproduce the setup.

Use a conventional `src/sweep/` package. Keep the project name **Sweep**, while the import/package name stays lowercase `sweep`. Begin with these responsibilities:

```text
src/sweep/
  domain.py                  Normalized messages, decision inputs and results
  decisions/
    context.py               Builds and measures the model input
    laya.py                  Loads the pinned model and evaluates one question
    policy.py                Maps valid scores to archive or delete
  testing/
    fixtures.py              Loads and validates synthetic mailbox data
    mailbox.py               Reusable in-memory mailbox
  evaluation/
    __main__.py              Command-line entry point
    runner.py                Runs cases through the real decision pipeline
    metrics.py               Compares predictions with expected answers
    reports.py               Writes readable and machine-readable results
tests/
  fixtures/
    messages.jsonl           Synthetic mail only
    cases.jsonl              Preferences and expected answers
  ...                        Fast tests that do not need model weights
```

Add `pyproject.toml`, the chosen dependency lockfile and `.gitignore`. Exclude virtual environments, downloaded weights, generated reports and any future private fixtures. Do not add a server framework, database client or cloud deployment dependency to the evaluator just because the eventual application uses them.

## 2. Define reusable data boundaries

The Gmail integration and fake mailbox should both return the same normalized `Message` representation. The context builder should not need to know which provided it.

| Object | Contains | Must not contain |
| --- | --- | --- |
| `Message` | Opaque ID, thread ID, internal timestamp, sender/recipients, subject, body text, labels, attachment metadata | Expected action or evaluation explanations |
| `DecisionInput` | Preferences, current message and eligible earlier thread messages | Test labels, case IDs, family names or split membership |
| `DecisionResult` | Raw chosen option, validated option scores, final policy action, token accounting, timing and version metadata | Gmail credentials or permission to execute arbitrary actions |
| Evaluation case | Target message reference, preferences, expected outcome, explanation and dataset split | Runtime secrets or real user mail |

Use explicit field selection when building `DecisionInput`. Never serialize an entire evaluation case into Laya's input. Otherwise a seemingly accurate model could simply be reading the expected answer.

The production decision function should be reusable by both the evaluator and the eventual worker. The evaluator adds scoring and reporting around it; it should not grow a separate imitation of the production prompting code.

## 3. Create synthetic messages and separate answer records

**JSONL** means one JSON record per line. The examples below are formatted across lines for readability; their future JSONL versions would each occupy a single line.

Example message in `messages.jsonl`:

```json
{
  "schema_version": 1,
  "message_id": "msg_0001",
  "thread_id": "thr_0001",
  "internal_date_ms": 1790064000000,
  "sender": "receipts@example.test",
  "recipients": ["alex@example.test"],
  "subject": "Your purchase receipt",
  "body_text": "Your receipt is attached. Please retain it for your records.",
  "labels": ["INBOX", "UNREAD"],
  "attachments": [{"filename": "receipt.pdf", "media_type": "application/pdf"}]
}
```

Example evaluation case in `cases.jsonl`:

```json
{
  "schema_version": 1,
  "case_id": "case_0001",
  "target_message_id": "msg_0001",
  "preferences": "Retain receipts. Discard expired promotional offers.",
  "expected_action": "archive",
  "expected_error": null,
  "expectation_reason": "The preference says to retain receipts; Archive keeps this message.",
  "family_id": "family_0001",
  "split": "development"
}
```

Validate IDs, references, timestamps, fields and action names before inference. Require exactly one expected result: an action or an error. For an invalid-input case, use `expected_action: null` and a specific `expected_error`; do not disguise an expected failure as an Archive.

Use opaque IDs such as `msg_0001`, rather than `delete-this-promotion`. Even metadata can accidentally reveal an answer. Evaluation annotations stay in the scorer and report, outside the context builder and model input.

Begin with about 40 deliberate English cases, covering both actions and error behavior:

- Obvious disposable mail and messages worth retaining.
- The same message under different user preferences.
- Prior replies that change how the target should be interpreted.
- Quoted text that should not be duplicated as fresh evidence.
- Instructions embedded in mail that attempt to override Sweep's rules.
- Long messages with crucial evidence near the beginning, middle or end.
- Empty, malformed and over-budget inputs.
- Attachment presence without pretending to have read the attachment.

Keep related variants in the same `family_id` and dataset split. Use development cases to choose wording and a threshold; use held-out cases to assess them afterward. Tuning on one version of a message and testing on a near-duplicate would inflate the result.

These fixtures are an engineering check, not a representative sample proving production accuracy. Any later real-mail examples must remain private unless their owners have explicitly authorized suitable publication.

## 4. Build the smallest useful fake mailbox

For this milestone, the fake mailbox needs only fixture loading, message lookup, earlier-thread lookup and reset. Store an immutable initial snapshot and return independent copies so one test cannot contaminate another. Sort prior thread messages by the same timestamp/tie-breaking rule used by the real pipeline; exclude later replies and duplicate quoted material from the selected context.

Use a small `Mailbox` interface so the next milestone can extend the same implementation with candidate paging and label changes. The reusable shape is:

```text
Fixture loader → Message objects → fake mailbox lookup
                                       ↓
Case preferences → DecisionInput → context → Laya → policy
                                                      ↓
Expected answers ───────────────────────────→ scorer → report
```

The expected-answer path only joins after the decision has been produced.

When building the full sweep engine next, extend this fake mailbox with:

- Candidate pages whose order deliberately does not imply newest first.
- Add/remove label operations that preserve unrelated labels.
- An operation log and deterministic failures on a chosen operation/attempt.
- A failure before a write, and a successful write followed by a lost response.
- Reset to the original fixture state for every independent scenario.

The fake mailbox must not invent exactly-once behavior that Gmail does not offer. For example, it should not magically deduplicate writes using Sweep's internal operation ID. The engine's saved intentions and recovery logic must earn that behavior.

This is an in-memory test adapter, not a mail server, inbox UI or complete Gmail emulator. A deterministic stub decision provider will let later job/retry tests run without loading Laya.

## 5. Load exactly one pinned Laya English model

The research baseline is `laya==0.3.5`, with SDK source commit `573e5b62696ba441230cd6be71d593331b5d23af`, and English model revision `1c5edc17a7acd8701df6fc341c0d179f1c62c982` from `convaiinnovations/laya`. Recheck artifact availability and compatibility when implementing, then lock all resolved dependencies. [SDK release](https://pypi.org/project/laya/0.3.5/), [model repository](https://huggingface.co/convaiinnovations/laya)

Download only the root English checkpoint, encoder configuration and tokenizer files to a local cache. Do not preload the multilingual or typed-decision models. The SDK accepts a local model path but not a revision argument; fetch the pinned snapshot separately. Keep its original hashes and any tokenizer normalization recorded, and avoid silent fallback downloads. Preserve third-party license notices.

Start with `device="cpu"` explicitly. A Mac can otherwise select Apple's MPS accelerator automatically. Stock SDK 0.3.5 uses float32 on CPU/MPS: approximately 843 MB of float16 files can require roughly 1.6 GiB for loaded parameters, with additional loading/runtime/activation memory. A 4 GiB Modal worker remains an unverified candidate. [Pinned loader implementation](https://github.com/NandhaKishorM/laya/blob/573e5b62696ba441230cd6be71d593331b5d23af/laya/agent.py)

Load once per evaluator process, outside the per-email loop. The same initialization pattern will later keep a model loaded across all emails in one worker.

## 6. Build and verify the 2,048-token input

| Part | Starting tokens |
| --- | ---: |
| Question and two answer criteria | 128 |
| Preferences | 256 |
| Message metadata | 64 |
| Current email and prior thread | 1,536 |
| Formatting and special-token reserve | 64 |
| **Total** | **2,048** |

Begin the content pool at 1,024 current-email tokens and 512 prior-thread tokens, borrowing unused space between them. A 1,000-character preference can exceed 256 tokens; preserve it and reduce other allowances when the remaining evidence is sufficient. The final rendered sequence must stay within the total budget.

Inspect the upstream sequence builder rather than assuming the high-level SDK forwards everything unchanged: it can clip instructions, option descriptions and state internally. Configure the relevant limits and verify the exact tokenized sequence reaching inference, including special tokens. [Sequence builder](https://github.com/NandhaKishorM/laya/blob/573e5b62696ba441230cd6be71d593331b5d23af/laya/common.py)

Tests should deliberately place essential information near boundaries. Record omitted sections and fail explicitly if necessary evidence cannot fit. Truncating required evidence and then confidently classifying the remainder is not a successful evaluation.

Use one `choice` question named `disposition` with `archive` and `delete` criteria. The question explains that Archive retains the message and Delete moves it to Trash. Keep system instructions and user preferences distinguishable from untrusted email text. Do not send fixture expectations or a generated explanation request.

## 7. Validate outputs and apply one policy

Laya returns structured scores rather than generated text. Validate the expected two option names, finite scores in range, probability consistency and the raw chosen option. Its generic confidence and act probability are separate quantities; they are not substitutes for the delete-option probability.

Save the raw model choice and scores. Then a separately versioned policy maps valid scores to the final Archive/Delete action. Prefer Archive when a valid evaluation is ambiguous; choose any delete threshold using development cases rather than assuming a score is calibrated. The policy does not require a second model call.

Malformed output or insufficient evidence yields an explicit error. It must not become a successful Archive by default. For the eventual worker, that means stopping at the failed item while preserving earlier confirmed results.

Upstream warns of overconfidence and weak results on some decision benchmarks. Evaluate Sweep's actual task before treating a score as reliable. [Model limitations](https://huggingface.co/convaiinnovations/laya#honest-limits)

## 8. Run cases and produce the report

The intended command, **after implementation**, is:

```sh
python -m sweep.evaluation --messages tests/fixtures/messages.jsonl --cases tests/fixtures/cases.jsonl --device cpu --max-tokens 2048 --output reports/baseline
```

Use one runner that loads the mailbox/model, assembles each `DecisionInput`, invokes the shared production decision code, then joins predictions to expected answers in the scorer. Reset mutable mailbox state between independent scenarios.

Write a Markdown report for review and JSON/CSV for later comparison. Include:

- Every expected-versus-actual action, explicit error and incorrect deletion.
- Counts per expected action, prediction and example family; invalid evaluations reported separately.
- A confusion matrix showing expected actions against predicted actions.
- Delete precision (how many predicted deletes were correct) and recall (how many expected deletes were found); show denominators and `N/A` where undefined.
- Raw model results alongside threshold-adjusted policy results.
- Actual input tokens, omissions/errors and model/question/context/policy versions.
- Load time, first inference, warm median and 95th-percentile latency, input preparation time and peak process memory.
- Device/CPU, threads, software versions, repetitions and measurement methodology.

An always-Archive model must be visibly distinguishable from useful automation. Keep setup, first-call and warm timings separate. Local CPU measurements do not predict Modal CPU speed or Gmail network latency; later benchmarks repeat the same fixtures on the target runtime.

After the ordinary baseline works, run bounded 512/1,024/2,048/4,096-token stress cases to understand scaling. The selected starting budget remains 2,048; a longer accepted sequence does not establish better quality.

## What gets tested without a model

Fast tests should cover fixture validation and reset isolation, expected-answer exclusion, prior-thread selection, token-budget boundaries, malformed-output rejection, policy mapping and metric calculations. Use a deterministic fake predictor for these tests. They should not require model downloads, cloud accounts or network access.

Real-model evaluation is a separate explicit command. A synthetic fixture pass is evidence that the pipeline is wired correctly; it is not evidence that arbitrary real emails can be deleted safely.

## Completion criteria

One documented command reproducibly evaluates the fixtures using the pinned English model. The input and output contracts are checked; errors remain visible; actual timings and memory are recorded; every false delete can be inspected. The mailbox loader and context/decision modules are reusable by the subsequent sweep engine. No Gmail or database connection is needed for this milestone.

The next milestone uses the same fake mailbox to exercise complete jobs, partial completion and lost responses, following the [architecture](architecture.md) and [database design](database.md).
