# Member settlement continuity

Authority: current Goal and latest user rulings → final Gmail contracts → exact
implementation/runtime. Relationships owns proposals, confirmation, repayment and
the canonical debt fold. This is one slice of the full delivery.

## User outcome and scope

A debtor sends one repayment proposal; the creditor confirms all or part of it,
rejects it or forgives the remaining obligation. Both can understand the actual
result and continue from a failed read without losing acknowledged work. An old
request cannot act on a replacement identity/debt or erase its current editing.

Use existing participant authorization, proposal/repayment command owners,
canonical queries, ledger binding and actual detail/history consumers. Preserve
OCC, original command identity and frozen currency. Do not create a second fold,
financial writer, generic workflow framework or parallel offline executor.

## Impact closure before construction

| Boundary | Actual entrance / consumer / current consequence |
|---|---|
| Entrances | `StatsRoutes` personal/all-ledger debt detail and receivables detail; debt-goal linked detail; shared `DebtDetailScreen` / `MemberProposalSection`. Web proposal forms use their existing command adapter |
| Identity | Host `DebtDetailViewModel` observes complete access, but proposal state keeps only debt ID plus a read generation. Proposal repository calls capture the then-current binding inside each suspended operation |
| Commands | `DebtProposalActions` owns the Android adapter for propose, withdraw, confirm, reject and forgive. Each call currently mints a key; backend command services retain participant validation, replay fingerprints, OCC and atomic facts |
| Old success exits | `onActionSucceeded` discards returned canonical data, clears the current form and refreshes. Read failure loses the acknowledged proposal; completion after another debt loads can clear its new draft. Repeated submits have no synchronous command guard |
| Real result consumers | Proposal pending/history cards, parent detail fold, repayment history, personal/all-ledger lists, receivables and debt-goal linked detail must follow the appropriate canonical result |
| Persistence and recovery | These actions are currently online and have no Room mutation family. Existing backend queries can recover canonical proposals/folds. Verify ACK loss and explicit continuation before changing command identity; never turn an unsent call into a durable success or add an offline owner merely for symmetry |
| Protocol and other containers | API and Web already use the same financial commands. Any altered command semantics require both consumers and their schema/replay tests to migrate. No Windows lifecycle work is opened |
| Direct verification | Existing proposal ViewModel/command regressions; new delayed-command, repeated-submit and acknowledged-result counterexamples; actual debtor/creditor task and parent/history refresh with original Room intent preserved |

The first change contains only direct tests and shared test fixtures. Admission and
implementation follow executable results. After construction, replace this table
with the final affected-consumer/retirement closure; keep CI hashes and logs in the
PR and external evidence. Unknown impact is not an exemption.
