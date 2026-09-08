# Web spending-goal editing

Authority: full current Goal and latest user rulings → final Gmail contracts →
exact source and runtime. Complete the Planning task without creating another
financial authority. Android submission continuity is CLOSED in #393, integrated
and independently main-qualified, including physical process/reconnect continuity.

## User outcome

From a spending-goal card, a household writer can edit its name, intended month,
limit and optional category. Validation or concurrent modification preserves
their input. Replaying the same submitted form retains the original key/body/OCC
and cannot create a second revision. A viewer or another ledger cannot perform
the write. Existing archive and canonical recycle recovery remain available.

## Impact closure before construction

| Boundary | Current evidence and required closure |
|---|---|
| Entries | Web goals has GET/create/archive only; its active cards lack edit. Add a real native form reachable from the card |
| Owner | API patch_goal currently owns inline idempotency claim, goal update and success commit. Share that narrow command with Web and retire the inline duplicate; goal_service remains the financial owner |
| Consumers | API/Android UpdateGoal dispatcher, Web card/editor and report queries must retain identical GoalResponse, currency and month meaning |
| Old success exits | Web edit has no successful task today. Preserve create/archive success; invalid/conflicting edits must not redirect away and discard input or silently acquire a fresh version |
| Persistence/protocol | Reuse Goal, existing request key table and expected_row_version. No schema/API epoch/Android outbox migration or second draft execution engine |
| Recovery | Refusal retains exact form fields/key/version; explicit review precedes a revised command. Restore continues through the shared recycle owner |
| Direct verification | Native form round trip, same-form replay, failed validation, cross-client OCC, viewer/foreign ledger and existing API goal idempotency tests; actual browser widths and keyboard submit |

## Finite qualification

Execute focused counterexamples before implementation, then targeted regression,
bounded review and exact candidate/main cloud qualification. A backend endpoint
or green structural test alone does not complete the Web task. Keep full Goal
delivery and Windows lifecycle HOLDs unchanged. Evidence and run IDs belong in
the PR/external qualification directory, not the product atlas.

## Impact closure after construction

The real card opens a native editor. Web and API now call one goal-update
transaction; the inline API transaction is retired. Existing GoalResponse,
operation/key fingerprint, OCC, currency binding, Android receipt and report
consumers keep their semantics. Refusal preserves the original input/key/token;
explicit review displays current facts and prepares a new proposal without writing.
Create/archive and the shared recycle owner remain their existing consumers.
Executed cloud RED found all three missing-entry cases. Candidate qualification,
actual browser tasks and bounded review are still pending.
