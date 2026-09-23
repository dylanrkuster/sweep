# Standalone evaluator

**Implemented:** local CPU evaluation with Laya English, a reusable fake mailbox, exact context construction, policy validation and reports. Gmail and cloud services are not connected. See [development](development.md) for commands and [baseline results](baseline.md) for measured behavior.

## One shared decision path

```text
Preferences + current email + earlier thread
    → context → Laya → validated scores → archive/delete policy
                                        → evaluator compares expected answers
```

`decisions/engine.py` is reusable by the future worker. It receives `DecisionInput`, never an evaluation case or expected answer. Scoring lives separately in `evaluation/`.

## Decision contract

One `choice` question, `disposition`, offers:

- **Archive:** retain the message outside Inbox and mark it read.
- **Delete:** move it to recoverable Trash and mark it read.

The evaluator simulates decisions; it changes no mailbox. The runtime returns both option probabilities and the raw choice. The policy rejects missing, non-finite or inconsistent scores. It deletes only when the delete score reaches the configured threshold; otherwise it archives.

The default threshold, **0.8**, is experimental and uncalibrated. A score is not a proven probability of correctness. Invalid input or model output remains an error, never a successful Archive.

## Context budget

| Section | Starting tokens |
| --- | ---: |
| Question and options | 128 |
| Preferences | 256 |
| Current-message metadata | 64 |
| Current email | 1,024 |
| Earlier thread | 512 |
| Formatting and special tokens | 64 |
| **Total** | **2,048** |

Sections can borrow unused space. Preferences must contain 1–1,000 characters. The final token sequence, including formatting and structural markers, must fit the total limit.

This baseline preserves complete current and eligible earlier-message content, including quotations. It has no semantic evidence selector. If the evidence cannot fit, it returns `context_overflow` instead of silently shortening the input. Other input errors are `invalid_preferences` and `empty_message`.

Prior context excludes the target, other threads, equal/later timestamps and identical duplicate records. Special-token spellings inside mail are JSON-escaped so they cannot become structural model markers; decoded text remains unchanged. IDs, mailbox labels and answer-key annotations are excluded from the model input.

## Pinned model

- SDK: [`laya==0.3.5`](https://pypi.org/project/laya/0.3.5/).
- English model: [`convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya/tree/1c5edc17a7acd8701df6fc341c0d179f1c62c982), revision `1c5edc17a7acd8701df6fc341c0d179f1c62c982`.
- Execution: CPU, float32, loaded once per process.

An explicit download fetches only the required English files and license notices. SHA-256 checks verify each file on download and load. The local manifest records revisions, sources and hashes. Dependencies are locked in `uv.lock`; no fallback model download occurs during inference.

Sweep passes prepared token IDs directly to Laya's model, avoiding the SDK's high-level truncation. Tests compare the sequence with the SDK and verify that collation preserves it. Sweep is MIT; the SDK and model retain their Apache-2.0 licensing.

## Fixtures and reports

The original five-message seed remains unchanged. `tests/fixtures/evaluation/` adds 43 messages and 40 cases: 26 development and 14 held-out. Expected outcomes include 18 archive, 14 delete and eight input errors.

Messages and answers use separate JSONL files. Cases reference a message and specify preferences, an expected action or error, a family and a split. The loader rejects broken references and families or threads crossing splits. Related variations must stay together.

Each run writes Markdown, JSON and CSV with:

- Expected versus actual decisions, raw scores, errors and a confusion matrix.
- Delete precision/recall with denominators; undefined ratios remain N/A.
- Exact token counts, omissions, versions and fixture hashes.
- Load time, first inference, warm median/p95 and peak process memory.

Development and held-out results remain separate. Repetitions are reported as attempts, not additional unique examples. Failed inference attempts count in timing statistics; expected validation failures are separate from action accuracy. Existing report directories are not overwritten.

## Next work

Improve the prompt or model using development cases, then evaluate fresh held-out examples. The current conservative policy archives every valid baseline case, so decision quality is the next gate before building real mailbox mutations. Hosting location remains a separate product decision.
