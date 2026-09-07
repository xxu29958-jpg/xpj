# Member settlement continuity

Authority: current Goal and latest user rulings → final Gmail contracts → exact
implementation/runtime. Relationships owns proposals, confirmation, repayment and
the canonical debt fold. This is one slice of the full delivery.

## User outcome and scope

A member first sees whom the obligation involves and its canonical remaining
amount, then sends one repayment proposal; the creditor confirms all or part of it,
rejects it or forgives the remaining obligation. Both can understand the actual
result and continue from a failed read without losing acknowledged work. An old
request cannot act on a replacement identity/debt or erase its current editing.

Use existing participant authorization, proposal/repayment command owners,
canonical queries, ledger binding and actual detail/history consumers. Preserve
OCC, original command identity and frozen currency. Do not create a second fold,
financial writer, generic workflow framework or parallel offline executor.

## Impact closure

| Boundary | Before → implemented closure |
|---|---|
| Entrances | Personal/all-ledger and receivables detail in `StatsRoutes`, plus debt-goal linked detail, share `DebtDetailScreen`. Forms/actions capture the rendered `DebtTask`; proposal/history panels appear only for that binding and debt |
| Identity | Debt-ID-only proposal/history targets → one immutable task containing the complete logical binding and debt ID. Repository reads/writes bind exactly to it; task replacement cancels old proposal work, revocation stops writes, and history cannot reuse a same-ID/version result from another binding |
| Commands | Five repeated Android request methods that mint per-call keys → one typed `DebtProposalActions.submit(task, command, key)` adapter for the same five server commands. The ViewModel admits one active call and retains the original key for an unchanged explicit retry |
| Old success exits | Discarded acknowledgements plus a fold-change counter → canonical proposal upsert or committed Debt adoption. A failed follow-up read retains the acknowledged result. Superseded completions cannot clear a new form or overwrite a newer parent fold |
| Task understanding | Known creditor hidden as generic member and remaining amount concealed → existing batched participant query names the opposite party across API/Web list/detail. Android/Web show the frozen-currency remaining amount before supporting details; supplied meaningful labels and private-ledger redaction remain |
| Result consumers | Parent summary adopts the canonical fold; its binding/debt/version refreshes repayment history. Back navigation retains existing personal/all-ledger, receivables and goal refresh paths. A confirmed proposal is labelled as this repayment being confirmed; only a cleared Debt claims settlement. No local repayment/balance calculation is introduced |
| Persistence/recovery | Commands remain explicitly online; an in-memory unchanged retry keeps its key. Reentry reconciles canonical proposal/fold/history through existing queries. No second Room family, offline executor or success claim for unsent work; existing durable intents remain byte-for-byte preserved in the real Room fixture |
| Protocol/other containers | Endpoint bodies, API epoch, backend participant auth/OCC/idempotency/fact writers and database schema remain unchanged. Web keeps the same command services and gains the same participant/remaining projection. Windows lifecycle remains HOLD |
| Direct validation | Executed original RED: repeated-submit, replaced-task and discarded-ACK tests; creditor identity API paths and Android visible remaining. Candidate adds original-key/binding/role/noncooperative response/parent-history tests and a real detail-screen + Room graph path: partial confirm with ACK loss, failed reads, history, reentry and forgiveness |

## Qualification state

Implementation is under qualification. Short local source analysis passes; final
candidate cloud checks, bounded review, physical debtor/creditor use and independent
merge-main qualification are still required. The earlier split-save Connected
waiting-receipt timeout remains an explicit final regression subject. Exact hashes,
run IDs and logs belong in [PR #392](https://github.com/xxu29958-jpg/xpj/pull/392)
and external evidence, not this product contract or the atlas.
