# Manual creation continuity

## User outcome and boundary

A submitted Android manual expense is saved durably before transport. Reopening
the app or losing an acknowledgement cannot change its money, create a fresh
intent, or overwrite a newer confirmed record with an older creation response.
Web drafts remain until the original command's acceptance is proven. This slice
continues the currency package; it does not close that package or the full Goal.

Use the existing manual creation service, Outbox, Room database, expense fact and
API idempotency receipt. No second queue, receipt state machine or currency owner.
Financial facts, attachments, identities and existing offline payloads remain
intact. Historical FX correction and Windows lifecycle work stay outside this slice.

## Impact closure before construction

| Boundary | Affected entry or consumer and required closure |
|---|---|
| Submission | API manual create, native Web form/browser draft and three Android sheet entries. Capture one original client reference, money, body and binding; expose real local-save versus server-acceptance feedback |
| Fact and receipt | `create_manual_expense` owns fact/revision/associations and the original typed receipt in one transaction. Preserve existing request fingerprints and authenticated device-scoped local references; replay the saved response without reading current money |
| Local persistence | Existing `enqueueLocalCreate`, Outbox admission and optimistic `ExpenseEntity` must commit in one Room transaction under the existing binding lease. Schedule only after commit and preserve the negative local identity |
| Sending and recovery | `CreateExpenseDispatcher` remains the sole Android sender. ACK loss replays the same body/reference; refusal keeps the row and never reports Done. Existing stop, conflict and binding controls remain authoritative |
| Read consumers | Web acknowledgement and both Android sync entries; ledger optimistic/cache rows, server-identity promotion and chained local-reference commands. An old creation receipt may establish identity but cannot replace a newer cached fact or refresh another command's OCC |
| Legacy | Existing key/fingerprint with no original receipt requires explicit review of the existing fact, retaining input and its key. Never manufacture an original receipt from the latest row or a later confirmation revision |
| Old success exits | Retire Android direct HTTP/fallback creation, IOException-only admission, non-atomic queue/cache publication, server latest-row creation replay and unproven Web draft auto-acknowledgement. New API creation requires a client reference, with compatibility negotiation updated before business validation |
| Direct proof | Native/API original-response replay after edits and pending-to-confirmed change; transaction rollback/concurrency; Web draft/receipt continuation; real Room rollback/reopen/ACK loss and monotonic identity promotion; actual sheet and sync consumers |

## Construction and qualification

Write direct counterexamples first. Preserve complete legacy original-money
payload bytes; never add a newly guessed home currency. Move only necessary
tests and constructors to the real command contract. Long PostgreSQL and Android
qualification runs in cloud/isolated environments; no long local suite.

After implementation, recheck the table against actual producers and consumers,
physically remove the replaced exits, then perform bounded review and exact-head
qualification. Keep run logs and SHA history in qualification evidence, not this map.

## Impact closure after construction

- Manual create now claims the original device-scoped key and commits the fact,
  initial revision, associations and typed receipt together. Replay returns that
  receipt; a legacy fact without it stays visible for review. Web retains the
  original form and offers that fact directly without falsely acknowledging it.
- Android publishes its existing Outbox row and local projection in one Room
  transaction. The dispatcher is the sole sender; it validates the original
  money and receipt identity before promotion. An older receipt cannot replace
  a newer cache record. Invalid receipts and incompatible clients never mean Done.
- Local-reference successor commands retain their original token and body. The
  backend resolves an unseen zero token only from the original creation receipt.
  A missing receipt does not prevent a previously accepted successor replay;
  it cannot authorize a fresh confirm/reject through an old terminal-state exit.
- Both sync entries expose original manual submissions. A local negative ID
  opens its submission status; server facts use positive IDs. Stopping a failed
  submission atomically removes only its unpromoted local projection and queue
  row, without undoing a possible server acceptance. All three manual entries
  share a save result and a reachable original-submission action; the confirmed
  stream never includes a fabricated local monetary projection. That action
  carries the original reference, not a temporary cache ID. Accepted navigation
  reads the verified expense ID saved with Done in the existing Outbox receipt;
  normal refresh, identity merge or cache removal cannot erase that association.
- API manual creation requires the original reference. Backend and Android
  compatibility versions move together, with negotiation before body validation.
  Direct HTTP producers retain one reference per task and reuse it on retry;
  the OpenAPI snapshot follows the actual request contract.

Status: implemented candidate; bounded review and exact
cloud/real-consumer qualification remain open. The direct producers above include
real Room rollback/reopen/receipt promotion, native Web receipt review, API replay
and protocol refusal; short pure tests do not substitute for those runtime gates.

Qualification corrections retain the same product commands: the legacy receipt
review ID is now explicit in ErrorResponse/OpenAPI; the Room rollback producer
requires its real owner binding. Physical-size advisory keys are selected once,
without weakening hard debt checks. Hosted ordinary jobs allow 15 minutes for the
observed full test run plus setup/cleanup. Desktop browser qualification waits
for the intended main document's load before starting the unchanged probe budget;
a real delayed multi-document navigation reproduces the previous false failure.
Connected execution keeps a 15-minute task bound across direct/GitHub/Gitea
callers; GitHub still bounds compilation plus all qualification at 18 minutes.
The previous 10-minute cutoff interrupted a progressing 255-case suite after
248 cases with no assertion failure. Per-test waits and receipt/crash/count
qualification are unchanged; partial execution cannot qualify the candidate.
