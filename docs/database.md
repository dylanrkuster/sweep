# Database design

**Proposed schema:** this describes the Firestore records to implement. Firestore is Sweep's saved memory; Gmail remains the actual mailbox. Source is MIT-licensed, but every production record below remains private.

[README](../README.md) · [Product scope](product.md) · [Architecture](architecture.md) · [Evaluator plan](evaluator-plan.md)

## Documents, collections and IDs

Firestore stores **documents** containing named fields, grouped into **collections**. Think of a collection as roughly a table and a document as roughly a row. A document may have subcollections, such as the emails selected for one job. Firestore does not enforce SQL foreign keys; our Python code checks relationships and allowed state changes. [Firestore's data model](https://firebase.google.com/docs/firestore/data-model)

```text
users/{googleSub}
  requests/{nonceHash}
credentials/{googleSub}
oauthStates/{stateHash}
jobs/{randomJobId}
  items/{zeroPaddedOrdinal}
budgets/{periodId}
```

`googleSub` is the stable subject from a verified Google identity token, not an email address. Job IDs are random opaque strings. Item IDs such as `00000000` express the position in a job. A message can appear in a later sweep if it becomes unread again; its Gmail ID is not a permanent global exclusion key.

All records carry `schemaVersion`. Store timestamps as Firestore Timestamp values and counts as integers. Timestamp strings and identities in the shortened JSON examples below are synthetic illustrations.

## 1. Users: settings and one active job

Path: `users/{googleSub}`.

| Fields | Meaning |
| --- | --- |
| `schemaVersion`, `createdAt`, `updatedAt` | Format and lifecycle information. |
| `preferencesText`, `preferencesVersion` | Saved instructions, initially up to 1,000 characters; version increases after edits. |
| `authorizationStatus` | `connected`, `reconnect_required` or `disconnected`. |
| `activeJobId` | Current sweep, or `null`; prevents overlapping sweeps. |
| `latestJobId` | Retrieves the latest summary directly. |
| `disabledAt` | Stops new work during account disconnection/removal. |

```json
{
  "schemaVersion": 1,
  "preferencesText": "Archive bills and messages needing a reply. Delete promotional newsletters.",
  "preferencesVersion": 3,
  "authorizationStatus": "connected",
  "activeJobId": "job-example-A7",
  "latestJobId": "job-example-A7",
  "disabledAt": null
}
```

Starting a sweep creates the job, sets `activeJobId` and consumes its submission token in one transaction. Two clicks cannot both claim an idle account. Completion clears the pointer only if it still refers to that job. An unresolved mailbox write keeps the account blocked until recovery is safe.

## 2. Credentials and authorization handshakes

Path: `credentials/{googleSub}`. A refresh token lets the worker obtain short-lived Gmail access after the interface request ends. It is encrypted, stored separately from settings and never returned to Gmail cards. [Google's authorization flow](https://developers.google.com/identity/protocols/oauth2/web-server)

| Fields | Meaning |
| --- | --- |
| `encryptedRefreshToken`, `nonce`, `keyVersion` | Authenticated-encryption ciphertext, its unique nonce and which private key can decrypt it. |
| `grantedScopes` | Permissions actually granted. |
| `credentialVersion` | Detects a reconnection while older work is running. |
| `createdAt`, `updatedAt`, `revokedAt` | Lifecycle and replacement information. |
| `lastAuthErrorCode` | Sanitized connection failure code. |

Use a maintained encryption library, bind the account and credential version as authenticated metadata, and keep keys in Modal Secrets rather than Firestore. Access tokens remain in process memory. Reconnection must not replace a valid refresh token with an empty value when Google omits a new one. Key rotation retains the old key until all relevant records are re-encrypted.

`oauthStates/{stateHash}` holds a short-lived connection handshake: `ownerSub`, `sessionBindingHash`, `createdAt`, `expiresAt`, `consumedAt`, and an allowlisted `redirectKey`. If the selected flow uses a PKCE verifier, store it encrypted with its nonce and key version.

The browser receives an unpredictable state value; the database stores its hash. The callback verifies the binding, atomically consumes the record and rejects expired/reused values. It must also verify that the Google account granting access has the same verified subject as the initiating user and granted every required scope. Valid state alone does not prove account equality.

Disconnection stops new work and settles outstanding operations before revoking and removing credentials. Revocation failures must remain visible for retry.

## 3. Submission records: repeated requests stay harmless

Path: `users/{googleSub}/requests/{nonceHash}`.

The API issues a short-lived unpredictable start token with the card. Its record contains `createdAt`, `expiresAt`, `consumedAt`, `requestFingerprint` and `jobId`. The fingerprint binds normalized count and preferences version to that submission.

A retry with the same token and parameters returns the same job. Reusing it with different parameters is rejected; a fresh sweep needs a fresh token. This is **deduplication**: repeated network delivery does not create repeated work. Unknown or expired tokens never create jobs, even after old records are cleaned up. A job ID by itself grants no access.

## 4. Jobs: one sweep and its summary

Path: `jobs/{randomJobId}`.

| Fields | Meaning |
| --- | --- |
| `ownerSub`, `requestId` | Account and accepted submission. |
| `status` | `discovering`, `queued`, `running`, `reconciling`, `completed`, `failed` or `needs_reconciliation`. |
| `requestedCount`, `selectedCount` | Requested N versus messages actually found. |
| `selectionQuery`, `selectionCutoff`, `selectionComplete` | Eligibility, discovery boundary and whether the fixed queue is ready. |
| `preferencesSnapshot`, `preferencesVersion` | Instructions frozen for this run, independent of later edits. |
| `versions`, `contextBudget` | Exact model/tokenizer/context/policy/calibration versions and the agreed 2,048-token allocation. |
| `nextOrdinal`, `counts` | Next unresolved position and confirmed summary totals. |
| `lease` | Owner invocation, generation, expiry and heartbeat. |
| `dispatch` | Pending flag, phase, generation, due time, attempts and invocation ID. |
| `budgetReservation` | Capacity accounting for accepted work. |
| `createdAt`, `startedAt`, `finishedAt`, `updatedAt` | Lifecycle timestamps. |
| `failure`, `cleanupAfter` | Sanitized failure information and retention deadline. |

```json
{
  "schemaVersion": 1,
  "ownerSub": "google-sub-example-01",
  "status": "running",
  "requestedCount": 20,
  "selectedCount": 12,
  "selectionComplete": true,
  "preferencesVersion": 3,
  "preferencesSnapshot": "Archive bills. Delete promotional newsletters.",
  "nextOrdinal": 5,
  "counts": {
    "processed": 4,
    "skipped": 1,
    "remaining": 7,
    "unresolved": 0,
    "actions": {"archived": 2, "deleted": 2, "markedRead": 4}
  },
  "lease": {
    "workerId": "worker-example-8",
    "generation": 2,
    "expiresAt": "2026-09-22T12:07:00Z"
  },
  "dispatch": {"pending": false, "phase": "process", "generation": 2}
}
```

The accounting rules are:

```text
processed = archived + deleted
markedRead = processed
remaining = selectedCount - processed - skipped
unresolved is a subset of remaining
```

`deleted` means confirmed placement in Trash with unread status removed, never permanent deletion. Selecting fewer than N is normal. An uncertain current item is distinguished from later untouched items.

The `dispatch` map is a saved to-do note. Saving it with the job closes the gap where the database write succeeds but the process crashes before submitting work. Recovery retries pending dispatches. Duplicate invocations still must claim the job; a submitted call does not prove completion.

## 5. Items: one selected email at a fixed position

Path: `jobs/{jobId}/items/{zeroPaddedOrdinal}`. Separate documents avoid growing one job beyond Firestore's document-size limit.

| Fields | Meaning |
| --- | --- |
| `ordinal`, `messageId`, `threadId`, `internalDateMs` | Fixed order and Gmail references; only the selected message is authorized for mutation. |
| `status`, `attempts` | Stage and bounded retry count. |
| `beforeLabels`, `beforeHistoryId` | Relevant mailbox state observed before the change. |
| `decision` | Model choice, final archive/delete action, policy version and optional scores/token counts. |
| `labelIntent` | Exact permitted label IDs to add/remove. |
| `operationId`, `leaseGeneration`, `writeStartedAt`, `writeDeadlineAt` | Identifies the attempted mutation and its owning worker. |
| `outcome`, `countedAt`, `completedAt` | Confirmed result and whether it entered the summary. |
| `lastErrorCode`, `reconciliationStatus` | Sanitized failure and uncertain-operation state. |

```json
{
  "schemaVersion": 1,
  "ordinal": 5,
  "messageId": "message-example-6",
  "threadId": "thread-example-2",
  "internalDateMs": 1790000000000,
  "status": "intent_saved",
  "beforeLabels": ["INBOX", "UNREAD"],
  "decision": {
    "modelChoice": "archive",
    "action": "archive",
    "policyVersion": "binary-mvp-v1"
  },
  "labelIntent": {"add": [], "remove": ["INBOX", "UNREAD"]},
  "operationId": "operation-example-6",
  "leaseGeneration": 2,
  "outcome": null,
  "countedAt": null
}
```

Archive removes `INBOX` and `UNREAD`. The preferred Delete intent adds `TRASH` and removes `INBOX` and `UNREAD`; integration must verify combined behavior and unrelated-label preservation. If separate Trash/read calls are needed, journal bounded `suboperations` individually and count success only after both are confirmed. [Gmail modification API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify)

Use Gmail's numeric internal timestamp for sorting and a deterministic message-ID tie-breaker. Do not assume list order. Partial selection writes are not runnable: set `selectionComplete` only after all expected item records exist, and never overwrite a frozen selection on duplicate dispatch.

## How an item becomes a confirmed result

1. Verify the worker lease, account permission and next item.
2. Fetch current Gmail state. Skip a fresh, unattempted item that became ineligible. Reconcile an already attempted uncertain write instead of treating it as fresh.
3. Build transient context and evaluate Laya. Invalid output or input/inference failure stops before mutation; it is not a third successful action.
4. Save the exact intent and operation identity before sending it to Gmail.
5. Send the allowed operation outside any database transaction, then confirm the required state, including absence of `UNREAD`.
6. In one Firestore transaction, verify the current lease and that the item is not already counted; save the outcome, update counts and advance the cursor together.

A repeated completion cannot increase counts twice. This does not promise exactly-once Gmail requests. Firestore transaction callbacks can rerun and cannot include Gmail, so external calls must never happen inside them. [Transactions](https://firebase.google.com/docs/firestore/manage-data/transactions)

A write timeout may follow a successful Gmail change. Reread relevant state and reconcile with the saved intention. Matching labels show current state but may not prove who changed them. Ambiguous outcomes remain unresolved; later items stay unattempted.

A **lease** is a temporary execution claim with an increasing generation. Database writes check that generation to reject stale workers. Expiry is not proof an old Gmail request stopped: establish termination and account for bounded deadlines before another mutation. If that cannot be established, keep the job blocked. A permanent failure with no uncertainty can release the account for a fresh sweep.

## 6. Capacity, indexes and retention

`budgets/{periodId}` records `provider`, `periodStart`, `periodEnd`, `allowance`, `safetyMargin`, `estimatedUsed`, `reserved`, `lastProviderCheckAt` and `admissionsPaused`. Firestore reads, writes and deletes are separate counters; compute can use integer microdollars of recurring credits.

Reserve conservative capacity before accepting work, including discovery, retries, checkpoints and cleanup. Settle reservations once and retain them until recovery proves abandoned work stopped. These are application estimates, not guaranteed provider capacity or authoritative invoices. Spark remains the initial no-billing database configuration; quotas and resource use must be measured with headroom. [Firestore quotas](https://firebase.google.com/docs/firestore/quotas)

An **index** speeds up a query. Most operations use a known document ID. Proposed compound indexes support recent jobs (`ownerSub` + descending `createdAt`), pending dispatch (`dispatch.pending` + `dispatch.notBefore`) and expired leases (`status` + `lease.expiresAt`). Avoid indexing preferences, ciphertext and other fields never searched.

Gmail cards call our API, never Firestore directly. Deny client database access through Security Rules. Python server libraries bypass those rules, so every API operation independently verifies ownership; service IAM permissions do not replace per-user checks. A separate credentials collection is a code boundary, not isolation from a service identity permitted to read the whole database. [Server access](https://firebase.google.com/docs/firestore/security/rules-conditions)

Do not persist raw email bodies, attachments, complete prompts or thread text, including in logs and crash reports. Keep only necessary references, preferences, compact decisions and recovery metadata.

Provisional retention is seven days for resolved items and thirty days for summaries; finalize it before deployment. Never delete active or unresolved records simply because they are old. Use bounded server-side cleanup within reserved quotas. Automatic TTL deletion, managed backups and point-in-time recovery require billing and are outside the initial free plan. Deleting a parent does not delete its subcollections, so cleanup must remove them explicitly and resume after interruptions. [Deleting nested data](https://firebase.google.com/docs/firestore/manage-data/delete-data)

Maximum N, recovery deadlines, calibrated decision thresholds and final retention remain implementation settings. The two-action product scope and 2,048-token context allocation are already selected. The [evaluator plan](evaluator-plan.md) starts with reusable fake messages before introducing these durable records.
