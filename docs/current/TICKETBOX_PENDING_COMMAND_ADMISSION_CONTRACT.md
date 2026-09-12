# Pending bill command continuity

The full Goal and final product contracts remain authoritative. This slice follows
the foreign-bill recovery integration; its current preparation base is a candidate,
not independently qualified main.

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
| Reject Undo | Pending currently starts its banner only from direct Synced success and calls a direct undo endpoint. Completion observation and original rejected version must remain correct; replacing all results with Queued without migrating this consumer loses an existing ability |
| Persistence/protocol | Existing mutation rows, original create/local references, receiptJson, binding transition and read adoption. The current undo endpoint has OCC but no original-command receipt; verify that direct path before selecting its migration |
| Shared helper callers | Acknowledge-items-mismatch also uses enqueueStateTransition; preserve its real caller if that helper changes, without silently opening all item/split editing |
| Direct proof producers | Actual RepositoryGraph + disk Room and ExpenseEditViewModel; existing repository state/save/recognition tests, Pending review/bulk/Undo tests, original dispatcher/OCC/binding tests |

## Minimum proof and closure

The prepared Room tests exercise online save admission and interruption of the
actual edit-page save/confirm chain. They have passed only short static checks;
business RED and subsequent GREEN have not run. Add only the direct controls needed
for atomic admission, binding refusal and preserved Undo when those owners change.
Do not preserve obsolete direct-Synced assertions by restoring the unsafe exit.

After construction, recheck the table against production callers and retire the
superseded methods/branches. Qualify the final exact candidate and integrated main
in cloud; no local long Gradle/PostgreSQL suite. No new financial fact owner,
parallel queue, 1.1 capability or Windows lifecycle work is authorized by this slice.
