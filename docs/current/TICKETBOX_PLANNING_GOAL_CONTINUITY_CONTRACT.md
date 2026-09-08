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

Executed counterexamples established that real Save persisted no Room intent,
malformed targets were discarded, and accepted goal responses were not retained.
Implementation publishes through GoalEditRepository and UpdateGoalDispatcher.
#393 is CLOSED: integrated and independently main-qualified, with bounded review
and physical offline Save → process termination → reconnect → canonical receipt.

## Before / after construction impact closure

| Boundary | Required closure and current evidence |
|---|---|
| Entries | List/create/detail and real Save now use the graph-wired GoalEditActions context. Stats remains a Reports goal-query consumer; all factories and real navigation harnesses migrate |
| Context | Debt-list currency dependency retired for spending create/detail. Existing runtime currency capability supplies code/scale; list/detail/Stats use explicit currency projection. Unknown currency has retry and does not render an editable CNY amount |
| Command owner | Reports direct update and unused fallback physically removed. GoalEditRepository publishes one original body/key/OCC under the existing atomic target/binding lease; UpdateGoalDispatcher is the sole Android PATCH writer |
| Old success exits | GoalSaveOutcome and optimistic totals retired. Room pending/failed/conflict remain separate from canonical Goal; dispatcher stores the accepted response in the existing receipt column, adopted before subsequent reads |
| Consumers | Spending list/create/detail track complete binding and live role; retained drafts stay within their task. Stats amount consumer uses query-projected currency. Shared archive now requires the rendered binding; debt-goal caller and direct tests migrate |
| Persistence/recovery | Existing flat UpdateGoal payload and Room schema remain. Unreadable targets fail visibly; bounded transient failures offer same-key retry, terminal refusals offer local withdrawal. Goal detail and both Sync Status entrances use the same GoalEditRepository recovery owner; the old generic UpdateGoal retry/drop bypass is retired. Existing scheduler/drain/status/retention owners remain; Room reopen proof is not OS process-death proof |
| Other writers | No backend schema, endpoint body, API epoch or Web financial-writer change. Currency fields already exist in runtime compatibility; the Goal currency addition is an Android read projection. Debt-goal link/deadline/integrity commands retain their existing owners |
| Direct verification | Existing goal ViewModel/repository/dispatcher/API/Web tests, plus real screen + production graph + disk Room proof that Save durably publishes before remote I/O; focused currency, binding, ACK/OCC and recovery counterexamples |

## Scope and qualification

Reuse existing Goal, currency capability, OutboxRepository and dispatcher
mechanisms. No new financial fact owner, generic workflow framework or second
offline executor. Backend schema/protocol changes require a concrete consumer
need and a full producer/consumer check. Windows lifecycle remains HOLD.

Actual Save and dispatcher counterexamples executed RED before their fixes.
The slice is qualified; the full Goal remains active. Long checks run in cloud; actual consumer work
uses the disconnected VM/cloud emulator. Exact hashes and run logs belong in the
PR and external qualification evidence, not the product atlas.
