# Import foreign bills and finish their review

## User outcome and scope

After importing/capturing foreign bills, the household can see which conversions
are incomplete, obtain the reference rates effective for the intended dates,
review original and home amounts, and explicitly confirm the bills. Provider
failure preserves the pending bills and gives retry or existing manual-rate entry.
A completed rate fetch is not a confirmed bill or a completed import/review task.

Goal/latest rulings and final Product contract sections 6.2/7/8.1 govern this task.
Reuse the modular monolith, provider/cache, BackgroundTask, Expense edit/confirm,
and actual Web/Android consumers. No importer-specific writer or second job engine.
No revaluation of confirmed facts, 1.1 expansion or Windows lifecycle work.
Start from qualified main 3503359d; #403 qualification remains the active priority.

## Impact before construction

| Responsibility | Required closure |
|---|---|
| Capture/import | CSV saved batches, direct import, manual entry and recognition-derived pending bills enter the same conversion continuation; provenance and original date/currency remain |
| Reference lookup | Fetch by requested historical date and preserve actual publication date/source. An arbitrary older cached row is not proof that the requested date was checked; do not invent a fixed age threshold |
| Cache and provider | Keep manual exact-date overrides and per-bill manual rates distinct. Concentrate any coverage evidence in the existing reference cache; retain configured transport and ECB provenance |
| Background execution | Existing persistent task owner reports queued/running/result/failure and supports bounded retry/restart; network work cannot hold the financial command transaction |
| Pending mutation | Revalidate status/OCC/current binding after fetching, preserve later user edits and confirmed snapshots, and use the existing Expense owner; conversion does not auto-confirm |
| Product consumers | Web/Android pending queue, bill editor/detail, import result and data-health entries identify blocked bills and return to review; Owner FX status describes actual relevant outcome |
| Shared rate consumers | Debt member FX, refund/reversal money and shared money projections also call resolve_payload_rate; determine their acquisition/recovery and preview contracts before changing shared lookup semantics, with direct regression proof |
| Old exits | Retire latest-sync-as-historical-success, cache-before-date-as-coverage and confirm-time hidden FX refresh; a changed conversion requires a separate pending revision and human review |

## Minimum proof

TDD through actual imports/pending commands: old unrelated cache, missing dated
rate, weekend actual publication date, exact manual override, provider failure and
retry, concurrent edit/confirmation, and real task-to-review consumers. Short local
checks; exact cloud qualification plus affected real client verification before
closure. This is construction preparation only; implementation/RED are pending.
