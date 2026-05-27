package com.ticketbox.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * ADR-0038 PR-2f: Android offline outbox row.
 *
 * Each row records exactly one mutation the user issued while the
 * device couldn't (or shouldn't) hit the server right then. The
 * outbox queue is drained later by ``OutboxDrainWorker`` (PR-2g),
 * which re-plays the mutation through the corresponding ApiService
 * call. The drain order is ``createdAt`` ascending and same-target
 * mutations are processed serially (PR-2g responsibility — the DAO
 * here just exposes ordered reads).
 *
 * Why a fixed schema instead of polymorphic columns per mutation
 * type: the v1.3 PR-2 series already standardised every mutation on
 * a ``expected_updated_at`` + JSON body shape, so a single Entity
 * row holds the entire request: route key (``type``), target
 * identifier, optimistic-concurrency token, and the JSON body the
 * matching ApiService call expects. New mutation types just add a
 * new ``PendingMutationType`` enum constant — no new Entity column.
 *
 * Status transitions are owned by ``PendingMutationStatus``:
 *   PENDING  → user enqueued, waiting for a chance to send
 *   IN_FLIGHT → WorkManager is replaying it right now
 *   CONFLICT → server returned 409 state_conflict; UI surfaces a
 *              "keep mine / drop mine" choice; user picks one and
 *              the row either retries with a fresh token or is
 *              deleted
 *   FAILED   → non-conflict error (4xx/5xx other than 409); user
 *              can retry manually
 *   DONE     → server accepted; row is kept briefly for audit /
 *              undo and then garbage-collected by cleanup_service
 *
 * ``targetId`` is the string form of whatever the server uses to
 * identify the row this mutation touches: ``"expense:42"`` /
 * ``"merchant_alias:abc-xyz"`` / etc. Composite keys (batch
 * mutations) use ``"expense_batch:42,43,44"``. The string is opaque
 * to the outbox itself; PR-2g's drain just needs equality matching
 * to enforce "same target_id is serial".
 *
 * ``expectedUpdatedAt`` is the ADR-0038 optimistic-concurrency
 * token (ISO-Z string from the row's ``updated_at`` field). For
 * mutations that don't take a token (creates / terminal lifecycle)
 * the field is blank.
 *
 * ``payload`` is the JSON the matching ApiService call requires.
 * Stored as TEXT; Moshi adapter is owned by the Repository layer
 * (the Entity is dumb storage).
 *
 * Indices: ``createdAt`` ascending drives the drain order;
 * ``(targetId, status)`` lets PR-2g check "is another mutation for
 * this row already IN_FLIGHT" without a full table scan; ``status``
 * lone-indexes the queue surface used by the conflict-banner UI.
 */
@Entity(
    tableName = "pending_mutations",
    indices = [
        Index(value = ["createdAt"]),
        Index(value = ["targetId", "status"]),
        Index(value = ["status"]),
    ],
)
data class PendingMutationEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    /**
     * Wire identifier for the route this row replays — see
     * ``PendingMutationType`` for the enum mapping. Stored as TEXT
     * (not Room TypeConverter) so a future Android release with a
     * new mutation kind doesn't need a schema migration; unknown
     * values surface as ``PendingMutationType.Unknown`` instead of
     * crashing the DAO.
     */
    @ColumnInfo(name = "type")
    val type: String,

    /**
     * String identifier of the row this mutation touches; see KDoc
     * on the Entity for the convention.
     */
    @ColumnInfo(name = "targetId")
    val targetId: String,

    /**
     * JSON body the matching ApiService call expects. The
     * Repository layer owns Moshi (de)serialisation; the Entity
     * stores opaque TEXT.
     */
    @ColumnInfo(name = "payload")
    val payload: String,

    /**
     * ADR-0038 optimistic-concurrency token. ISO-Z string. Blank
     * for routes that don't take a token (creates / terminal
     * lifecycle / upserts — see ALLOWLIST in
     * ``backend/scripts/_audit_mutate_token_coverage.py``).
     */
    @ColumnInfo(name = "expectedUpdatedAt")
    val expectedUpdatedAt: String,

    /** Stringified ``PendingMutationStatus``. */
    @ColumnInfo(name = "status")
    val status: String,

    /**
     * Bumped each time the drain worker retries this row. Used to
     * back off retries and to surface a "tried 3 times, please
     * check" hint to the user.
     *
     * [codex round-2 P2#4] fix: ``defaultValue = "0"`` matches the
     * ``DEFAULT 0`` in [AppDatabase.Migration8To9]'s CREATE TABLE.
     * Room's migration validator otherwise fails on the schema
     * mismatch between entity default (none → NOT NULL with no
     * default) and DB default (``0``).
     */
    @ColumnInfo(name = "retryCount", defaultValue = "0")
    val retryCount: Int = 0,

    /**
     * Last server message (Chinese, ADR-0038 contract) when the
     * row landed in ``CONFLICT`` or ``FAILED``. Null while
     * ``PENDING`` / ``IN_FLIGHT`` / ``DONE``.
     */
    @ColumnInfo(name = "lastError")
    val lastError: String? = null,

    /** Wall-clock when the row was enqueued (ISO-Z string). */
    @ColumnInfo(name = "createdAt")
    val createdAt: String,

    /**
     * Wall-clock when the drain worker last touched the row (ISO-Z).
     * Null while the row is still ``PENDING`` and hasn't been
     * picked up yet.
     */
    @ColumnInfo(name = "attemptedAt")
    val attemptedAt: String? = null,

    /**
     * Wall-clock when the row reached a terminal state (``DONE`` /
     * ``CONFLICT`` after the user picked an action / ``FAILED``
     * after the user dismissed it). Null while the row is still
     * being worked on. Used by the cleanup path to garbage-collect
     * old completed rows.
     */
    @ColumnInfo(name = "completedAt")
    val completedAt: String? = null,
)
