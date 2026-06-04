package com.ticketbox.domain.model

/**
 * ADR-0042 Slice C: outcome counts of a confirmed-expense batch field edit,
 * which the repository fans out into N independent ``PatchExpense`` mutations
 * (one per selected expense, each with its own row_version token + idempotency
 * key). Partial success is first-class — unlike the atomic ``/web`` batch
 * endpoint, a stale row conflicts or queues independently of its siblings:
 *
 *  - [synced]: the direct PATCH committed online.
 *  - [queued]: the network was down; the edit is enqueued in the outbox and the
 *    worker replays it on connectivity-up.
 *  - [failed]: a hard error (e.g. a 409 from a row edited elsewhere since the
 *    last sync) — resolvable via the existing keep-mine flow after a re-sync.
 *
 * The ViewModel turns these into an honest snackbar listing whichever buckets
 * are non-zero, e.g. "已更新 X 笔，Y 笔已加入同步，Z 笔需重新同步".
 */
data class BatchApplyResult(
    val synced: Int = 0,
    val queued: Int = 0,
    val failed: Int = 0,
) {
    val total: Int get() = synced + queued + failed
}
