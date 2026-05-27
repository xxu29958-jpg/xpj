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
    /**
     * Server returned 2xx; outbox row transitions to DONE.
     *
     * ``newUpdatedAt`` is the server-side ``updated_at`` from the
     * response body when the route mutated a versioned row. The
     * drain engine cascades this token onto same-target PENDING
     * rows so a chain of offline mutations against the same row
     * doesn't fake-conflict itself: A's outbox row carried the
     * old token T0; after A lands the server is at T1; B's outbox
     * row was enqueued with T0 (the only token the client knew at
     * the time) — without the cascade, B replays with T0 and
     * server says 409. With the cascade, B's row is rewritten to
     * T1 before it dispatches.
     *
     * Routes that don't return a token (creates / terminal
     * lifecycle that has its own state machine) pass ``null``.
     */
    data class Success(val newUpdatedAt: String? = null) : DispatchResult

    /**
     * Server returned 409 ``state_conflict``. The row goes to
     * CONFLICT status; the UI surfaces a "keep mine / drop mine"
     * banner and the user picks one.
     */
    data class Conflict(val serverMessage: String) : DispatchResult

    /**
     * Permanent failure that needs user attention — typically a
     * 4xx the user must resolve (e.g. validation error in the
     * payload they typed) or a non-recoverable client-side bug
     * (Moshi can't parse the row's payload). Row goes to FAILED;
     * the drain engine will NOT auto-retry — the user has to
     * fix the input or dismiss the row.
     */
    data class Failure(val message: String) : DispatchResult

    /**
     * Transient failure that the drain engine should retry on a
     * later tick — network blip, server 5xx, timeout. Row stays
     * PENDING; ``retryCount`` and ``lastError`` are recorded so
     * the UI can warn after N attempts and the engine can apply
     * back-off.
     *
     * Splitting Failure / RetryableFailure is the [codex finding
     * P1#3] fix: previously a single transient network error
     * would mark the row FAILED, and FAILED rows are not picked
     * up by ``nextPendingBatch`` so the outbox effectively
     * stopped auto-replaying after one server hiccup.
     */
    data class RetryableFailure(val message: String) : DispatchResult

    /**
     * Server returned a "row no longer exists / already in a
     * terminal state" response (404, or status-specific 409 like
     * ``items_sum_not_in_mismatch``). Row is removed from the
     * outbox without bothering the user — the divergence already
     * happened and there's nothing meaningful to "keep" or "drop".
     */
    data class Discarded(val reason: String) : DispatchResult
}
