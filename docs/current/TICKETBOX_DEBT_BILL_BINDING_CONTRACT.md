# Debt-bill preparation and original household binding

## Working contract

Goal and the three final product contracts require original user work to stay with its logical household identity. This slice begins at source `d22511909553edf3f6c09055c32f60b9fc26fb48` in the isolated `codex/debt-bill-binding-20260907` worktree. The parent upload slice is still under exact cloud qualification; this preparation does not qualify it or authorize an early protected merge. Root is the sole writer; the two existing independent agents are unavailable because their calls reached the account limit.

The outcome is bounded: a debt-bill image accepted for preparation under household A must not be sent or applied under a subsequently selected household B. Recognition remains a suggestion. The existing Debt creation command, durable Outbox, financial interpretation and explicit Save remain the only publication chain. No new draft persistence policy, automatic command, API wire field, Windows lifecycle action or visual redesign is included.

## Before-impact closure

- Entrances: the obligations-domain composer and the debt-list route both use `rememberDebtBillImageLauncher`. After the picker callback, it calls `markBillParsePreparing`, performs image preparation on IO, and later calls `parseDebtBillImage` or `billParsePreparationFailed` without a captured identity.
- Owners and consumers: DebtListViewModel owns parsing progress, prefill, draft currency and sheet-open feedback; DebtRepository owns the bound multipart call; the two real sheet hosts consume the same ViewModel state. Both route instances, all direct JVM callers and every DebtActions implementation are affected by any interface correction.
- Existing guard and uncovered interval: DebtRepository guards a request against a switch during HTTP, but binds the current session only after image preparation. A switch during preparation can therefore admit A's bytes into a new request for B. The preparation continuation has no way to identify its original attempt. Existing same-binding parse/pre-fill and viewer tests do not exercise this interval.
- Old success exits: an obsolete preparation/response cannot open a new household's sheet, replace its draft, clear another attempt's busy state, or show an unrelated failure. Valid same-identity recognition must still prefill the original currency-aware suggestion and await explicit Save.
- Persistence/protocol/recovery: recognition itself does not accept a financial command or enqueue an offline intent. Existing submitted Debt payload/key/identity and upload originals stay with their existing owners. A stale recognition continuation must refuse; it must not create a replacement command. There is no database or public protocol migration.
- Direct producers: add a gated current-ViewModel counterexample covering the real preparation-to-request boundary, retain existing positive/currency/viewer cases, and cover the actual bound repository call and both UI adapters after correction. Kotlin compilation, JVM, Lint and Connected qualification stay in cloud; local work is limited to short source checks.

## Qualification state

The source interval is identified. The first counterexample has been written before changing production code; it has not executed yet. Its fake request boundary observes whether the original bytes reach the phase where DebtRepository currently binds the active identity. The test must reject the old image before this boundary after a ledger change while leaving the new household's draft unchanged. Candidate and protected-main gates, formal review and after-impact closure remain required.
