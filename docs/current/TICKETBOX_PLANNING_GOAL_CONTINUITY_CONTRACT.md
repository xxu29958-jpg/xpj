# Planning goal continuity

Authority: current Goal and latest user rulings → final Gmail contracts → exact
code and runtime. Complete, strengthen and correct the task; migrate consumers
and physically retire replaced implementations. This is part of Planning and
cross-client continuity, not full Internal Beta RC completion.

## User outcome

A member can understand and edit a spending goal in its authoritative currency
and month, submit once, leave and return, and recover the original submission
after interruption or refusal. Queued work stays distinguishable from confirmed
progress. The real save control must publish through the existing UpdateGoal
outbox owner; a parallel direct writer must not survive the migration.

Current executable subjects: the real editor calls ReportsActions.updateGoal,
while updateGoalAllowingOffline has no production consumer; create/detail obtain
currency through DebtActions.listDebts; old operation results are guarded by goal
ID/load generation rather than the complete logical binding.

## Before-construction impact closure

| Boundary | Required closure and current evidence |
|---|---|
| Entries | SpendingGoalsRoute list/create/detail and SpendingGoalDetailScreen save; inspect all goal consumers before changing their shared contract |
| Context | Goal API response/list, Reports DTO/mappers and spending create/detail/list/overview; retire the unrelated debt-list currency dependency without substituting a default currency |
| Command owner | ReportsRepository direct update and unused offline fallback → existing UpdateGoal dispatcher as sole Android wire writer; one durable original key/body/OCC and exact logical binding |
| Old success exits | Direct canonical Goal and synthetic GoalSaveOutcome.Queued must become honest durable submission/confirmed result feedback; old optimistic totals cannot masquerade as recomputed facts |
| Consumers | Spending list/detail, Stats goal summary, debt-goal consumers of shared Goal/Reports contracts, real graph/factories and sync status; a shared response change must cover each producer and consumer |
| Persistence/recovery | Existing UpdateGoal rows, adapter, target parsing, retry/conflict/drop, complete binding, scheduler/drain, process restart and older payloads; preserve unsent rows and never settle an unreadable intent as done |
| Other writers | Backend/API/Web goal create/update/archive/restore and debt-goal links/deadline/integrity commands retain their financial owners; verify shared response impact rather than assuming they are unaffected |
| Direct verification | Existing goal ViewModel/repository/dispatcher/API/Web tests, plus real screen + production graph + disk Room proof that Save durably publishes before remote I/O; focused currency, binding, ACK/OCC and recovery counterexamples |

## Scope and qualification

Reuse existing Goal, currency capability, OutboxRepository and dispatcher
mechanisms. No new financial fact owner, generic workflow framework or second
offline executor. Backend schema/protocol changes require a concrete consumer
need and a full producer/consumer check. Windows lifecycle remains HOLD.

Start with executed RED on the actual save path, then implement and perform the
after-construction closure here. Long checks run in cloud; actual consumer work
uses the disconnected VM/cloud emulator. Exact hashes and run logs belong in the
PR and external qualification evidence, not the product atlas.
