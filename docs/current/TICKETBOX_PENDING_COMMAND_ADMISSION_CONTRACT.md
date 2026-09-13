# Pending bill command continuity

The full Goal and final product contracts remain authoritative. This responsibility
is part of the foreign-bill recovery integration: review found that its online
pending writer can still lose an accepted command when cache publication fails.
The current subject is a candidate, not independently qualified main.

## User outcome

Save, confirm, reject and recognition actions retain the user's original command
before any request can reach the server. Leaving the page, losing an ACK or failing
local publication must not lose the original key, binding, payload or reviewed OCC.
Save-and-confirm preserves both steps together. Queued intent is visibly pending;
it must not impersonate a confirmed financial fact. Preserve useful reject Undo.

## Impact closure before construction

| Responsibility | Actual affected entries and consumers |
|---|---|
| Submission | ExpenseEdit save/confirm/reject/not-duplicate/retry-OCR/recognize-text; Pending single actions, amount-patch followed by confirmation, continuous review and batch-ready confirmation |
| Original owner | Existing Expense repositories and bound Outbox admission. Reuse the existing worker, dispatchers, FIFO/OCC cascade, insertBatch and binding lease; retire migrated direct writer exits rather than adding an inline sender or polling engine |
| Result and recovery | Existing SaveOutcome/ExpenseStateOutcome, editor exit and pending-list reducers, Sync and Fact receipt/refresh consumers. A local acceptance message must remain understandable after navigation |
| Reject Undo | Pending seeds Undo from the original rejected receipt after command completion. Web single, bulk and duplicate-current reject/undo call `submit_expense_rejection` with a form-carried original key. A stale receipt must not undo a later rejection. |
| Persistence/protocol | Existing mutation rows, original create/local references, receiptJson, binding transition and read adoption. Reject/Undo must freeze the original acceptance using the existing server idempotency response_body; Undo consumes the original rejected version, never a later cascaded version |
| Shared helper callers | Acknowledge-items-mismatch also uses enqueueStateTransition; preserve its real caller if that helper changes, without silently opening all item/split editing |
| Direct proof producers | Actual RepositoryGraph + disk Room and ExpenseEditViewModel; existing repository state/save/recognition tests, Pending review/bulk/Undo tests, original dispatcher/OCC/binding tests |

## Minimum proof and closure

Room and unit producers already exercise online save admission, binding refusal,
completion-driven Undo, ACK-loss replay and a stale reject receipt that cannot
undo a newer rejection. Cloud Android fast on 28b0d649 executed those unit
producers. Qualify the next exact candidate in cloud after the current
Web/Android consumer and receipt-protocol migration. Do not restore
direct-Synced exits to satisfy an obsolete assertion.

After construction, recheck the table against production callers and retire the
superseded methods/branches. Qualify the final exact candidate and integrated main
in cloud; no local long Gradle/PostgreSQL suite. No new financial fact owner,
parallel queue, 1.1 capability or Windows lifecycle work is authorized by this slice.
