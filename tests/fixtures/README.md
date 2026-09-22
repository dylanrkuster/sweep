# Synthetic seed mailbox

These five invented messages and three expected-answer records exercise the data-loading foundation. They are a small development sample, not the full evaluator dataset or evidence of model accuracy. Every address uses the reserved `.test` domain; no real mailbox data is included.

`messages.jsonl` holds mailbox facts only. `cases.jsonl` refers to those messages and keeps preferences, expected results, and scoring annotations separate. The same message can appear in multiple cases with different preferences. A family and a thread must remain within one dataset split to avoid evaluating on closely related copies of examples used for tuning.

The receipt thread includes an earlier message and a later reply. Earlier-thread lookup must return only the earlier message when the receipt is the target, regardless of the records' order in the file. Appointment and receipt attachments contain metadata only; Sweep does not read their contents.

Each JSONL line is one complete JSON record. The loader checks every record before returning the dataset. Expected answers must never be copied into `DecisionInput` or a future model prompt.
