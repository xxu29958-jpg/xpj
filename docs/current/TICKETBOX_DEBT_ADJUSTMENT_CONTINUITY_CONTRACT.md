# Original debt-adjustment intent

This slice continues the whole-system Internal Beta RC Goal and the capability-first ruling. The final Product contract sections 6.4 and 9 own relationship facts and original-command recovery. The current source shows a missing Android continuity path: every direct `recordAdjustment` call generates a new key, while the backend can recover a committed response only under the original key and body. Closing the form also clears its submitted context. No duplicate financial posting has been demonstrated; the known consequence is loss of the original recovery path after an uncertain result.

## User outcome and owners

An authorized user adjusts one external debt with a signed amount and a reason. Local acceptance retains the original debt identity, label, currency, amount, reason, logical binding, payload revision, OCC and idempotency key before networking. Unknown results, protocol refusals and application restart retain that exact intent visibly. Retrying recovers the existing backend command under its original key; it neither guesses a fresh OCC nor creates a replacement adjustment. A confirmed conflict asks for reconciliation or explicit local-intent discard. The authoritative debt fold changes only through the existing backend adjustment command.

Reuse Room/Outbox, its session and expiry boundaries, the existing debt command, and current sync recovery entrances. The detail page and global recovery explain the original adjustment and distinguish local acceptance from committed financial fact. Retire the Android direct adjustment writer and migrate its real consumers. Other repayment, proposal, forgiveness, void and classification commands are outside this bounded change; their separate continuity gaps remain in the full Goal.

## Minimum proof and integration

First reproduce the present recovery failure through the actual client boundary. Then verify durable publication before networking, original-key response-loss recovery, unsupported/protocol/conflict retention, and unchanged binding/OCC/expiry semantics. A real Room/UI consumer must show original context after reopen and complete the actual save/recovery path. Existing backend adjustment idempotency and fold tests remain the server proof; expand them only if an executable gap requires it. Use short local source/contract checks and exact-candidate cloud Android/backend qualification, followed by bounded review and protected integration.

The branch begins at `ce192c10`, the current Income candidate, to reuse its corrected shared refusal model. That parent is still awaiting its own gates; it is not a qualified main baseline. Qualification of this dependent slice must follow actual integration of its parent. No local long Gradle/PostgreSQL test, no new financial subsystem, and no held Windows lifecycle work are authorized by this slice.
