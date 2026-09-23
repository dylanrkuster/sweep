# Synthetic evaluation corpus

43 fictional messages support 40 cases: 26 development and 14 held-out. Expected results are 18 archives, 14 deletes and eight validation errors.

- `messages.jsonl` contains mailbox facts only, using fictional `.test` addresses.
- `cases.jsonl` contains preferences and the separate answer key. Never send scoring fields to the model.

Coverage includes preference reversals, earlier replies, quoted evidence, instructions embedded in mail, unseen attachments and invalid inputs. Three oversized messages put necessary evidence at different positions; all expect `context_overflow`, not silent truncation.

Related messages and variants stay in one split. Use development cases for tuning; inspect held-out results afterward without tuning against them. These small, deliberate cases test behavior; they do not establish real-world accuracy.

The original fixtures one directory above remain the small loader demonstration. See the [development guide](../../../docs/development.md) for commands.
