package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType

/**
 * ADR-0038 PR-2g: contract that turns an outbox row back into a
 * server call.
 *
 * Each [PendingMutationType] registers exactly one implementation.
 * The drain engine picks a runnable row, hands it to the dispatcher
 * keyed by ``row.type``, and translates the [DispatchResult] back
 * into outbox status transitions. The dispatcher is intentionally
 * the only layer that knows the wire shape of each mutation — the
 * Repository and the Worker stay generic.
 *
 * Implementations are responsible for:
 * 1. Deserialising ``row.payloadJson`` into the Request DTO the
 *    matching ApiService method expects.
 * 2. Calling the ApiService method with both the payload AND
 *    ``row.expectedUpdatedAt`` (where the route requires a token).
 * 3. Translating the HTTP response into a [DispatchResult]:
 *      - 2xx → [DispatchResult.Success]
 *      - 409 ``state_conflict`` → [DispatchResult.Conflict] with the
 *        server's Chinese message
 *      - any other 4xx/5xx → [DispatchResult.Failure]
 *      - "the row's already been resolved by another path" /
 *        "the target was deleted" → [DispatchResult.Discarded]
 *
 * Why a Map<Type, Dispatcher> registry instead of a sealed-class
 * hierarchy: new mutation kinds will be wired one by one in
 * follow-up PRs (call sites in PR-2g.3, conflict UI in PR-2g.4,
 * etc). A registry lets each follow-up add exactly one dispatcher
 * class without touching the drain engine.
 */
interface OutboxMutationDispatcher {
    /** Wire identifier of the mutation kind this dispatcher handles. */
    val type: PendingMutationType

    /**
     * Replay [row] against the server. Must NOT mutate the outbox
     * itself — the drain engine owns status transitions.
     */
    suspend fun dispatch(row: OutboxRow): DispatchResult
}

sealed interface DispatchResult {
    /** Server returned 2xx; outbox row transitions to DONE. */
    data object Success : DispatchResult

    /**
     * Server returned 409 ``state_conflict``. The row goes to
     * CONFLICT status; the UI surfaces a "keep mine / drop mine"
     * banner and the user picks one.
     */
    data class Conflict(val serverMessage: String) : DispatchResult

    /**
     * Non-conflict error (other 4xx / 5xx, network failure). Row
     * goes to FAILED; the user can retry manually or the drain
     * engine will back off and try again with the next tick.
     */
    data class Failure(val message: String) : DispatchResult

    /**
     * Server returned a "row no longer exists / already in a
     * terminal state" response (404, or status-specific 409 like
     * ``items_sum_not_in_mismatch``). Row is removed from the
     * outbox without bothering the user — the divergence already
     * happened and there's nothing meaningful to "keep" or "drop".
     */
    data class Discarded(val reason: String) : DispatchResult
}
