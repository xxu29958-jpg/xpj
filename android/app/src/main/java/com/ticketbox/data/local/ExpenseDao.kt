package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

private const val SQLITE_BINDING_CHUNK_SIZE = 500

data class ConfirmedStreamPruneScope(
    val rootServerIds: Set<Long>?,
    val offsetPublicIds: Set<String>?,
)

data class ConfirmedStreamSnapshot(
    val roots: List<ExpenseEntity>,
    val offsets: List<ExpenseOffsetStreamEntity>,
)

/**
 * v0.4-alpha1 multi-ledger contract:
 *
 * Every confirmed query and upsert MUST filter by [ledgerId]. `serverId`
 * identifies a backend row only inside the active ledger cache; using it as a
 * global local key would let a bad or rebinding server response rewrite a
 * different ledger's cached row.
 */
@Dao
interface ExpenseDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveGoalSnapshots(snapshots: List<GoalQueryCacheEntity>)

    @Query("SELECT * FROM goal_query_cache WHERE bindingKey = :bindingKey AND timezone = :timezone AND queryKey = :queryKey")
    suspend fun goalSnapshot(bindingKey: String, timezone: String, queryKey: String): GoalQueryCacheEntity?

    @Query("DELETE FROM goal_query_cache")
    suspend fun clearGoalSnapshots()

    @Query("DELETE FROM goal_query_cache WHERE ledgerId = :ledgerId")
    suspend fun clearGoalSnapshotsForLedger(ledgerId: String)

    @Query("DELETE FROM goal_query_cache WHERE bindingKey = :bindingKey")
    suspend fun clearGoalSnapshotsForBinding(bindingKey: String)

    @Query("DELETE FROM stats_projection_cache WHERE bindingKey = :bindingKey")
    suspend fun clearStatsProjectionsForBinding(bindingKey: String)

    @Transaction
    suspend fun clearReadSnapshotsForBinding(bindingKey: String) {
        clearGoalSnapshotsForBinding(bindingKey)
        clearStatsProjectionsForBinding(bindingKey)
    }

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveStatsProjection(snapshot: StatsProjectionCacheEntity)

    @Query("""
        SELECT * FROM stats_projection_cache
        WHERE bindingKey = :bindingKey AND kind = :kind AND month = :month AND tag = :tag
          AND timezone = :timezone
        ORDER BY fetchedAt DESC
    """)
    suspend fun statsProjections(
        bindingKey: String, kind: String, month: String, tag: String, timezone: String,
    ): List<StatsProjectionCacheEntity>

    @Query("DELETE FROM stats_projection_cache")
    suspend fun clearStatsProjections()

    @Query("DELETE FROM stats_projection_cache WHERE ledgerId = :ledgerId")
    suspend fun clearStatsProjectionsForLedger(ledgerId: String)

    @Query(
        """
        SELECT * FROM expenses
        WHERE ledgerId = :ledgerId AND status = 'confirmed'
        ORDER BY COALESCE(expenseTime, confirmedAt, createdAt) DESC
        """,
    )
    fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>>

    @Query(
        """
        SELECT * FROM expenses
        WHERE ledgerId = :ledgerId AND status = 'confirmed'
        ORDER BY COALESCE(expenseTime, confirmedAt, createdAt) DESC
        """,
    )
    suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity>

    @Query(
        """
        SELECT * FROM expenses
        WHERE ledgerId = :ledgerId
          AND status = 'confirmed'
          AND streamDate IS NOT NULL
          AND streamSortTime IS NOT NULL
          AND streamSortId IS NOT NULL
          AND streamAmountCents IS NOT NULL
          AND lineageStatus IS NOT NULL
          AND lineageHomeNetCents IS NOT NULL
        ORDER BY streamDate DESC, streamSortTime DESC, streamSortId DESC
        """,
    )
    fun observeConfirmedStreamRoots(ledgerId: String): Flow<List<ExpenseEntity>>

    @Query(
        """
        SELECT * FROM expense_offset_stream
        WHERE ledgerId = :ledgerId
        ORDER BY streamDate DESC, streamSortTime DESC, streamSortId DESC
        """,
    )
    fun observeConfirmedStreamOffsets(ledgerId: String): Flow<List<ExpenseOffsetStreamEntity>>

    @Query("SELECT * FROM expense_offset_stream WHERE ledgerId = :ledgerId")
    suspend fun getConfirmedStreamOffsets(ledgerId: String): List<ExpenseOffsetStreamEntity>

    @Transaction
    suspend fun getConfirmedStreamSnapshot(ledgerId: String): ConfirmedStreamSnapshot =
        ConfirmedStreamSnapshot(getConfirmed(ledgerId), getConfirmedStreamOffsets(ledgerId))

    @Query("SELECT publicId FROM expense_offset_stream WHERE ledgerId = :ledgerId")
    suspend fun confirmedStreamOffsetPublicIdsForLedger(ledgerId: String): List<String>

    @Query(
        """
        SELECT * FROM expenses
        WHERE ledgerId = :ledgerId AND status = 'pending'
        ORDER BY createdAt DESC, serverId DESC
        """,
    )
    suspend fun getPending(ledgerId: String): List<ExpenseEntity>

    @Query(
        "SELECT * FROM expenses WHERE ledgerId = :ledgerId AND serverId = :serverId LIMIT 1",
    )
    suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity?

    @Query(
        "SELECT * FROM expenses WHERE ledgerId = :ledgerId AND serverId IN (:serverIds)",
    )
    suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity>

    @Query(
        """
        SELECT serverId FROM expenses
        WHERE ledgerId = :ledgerId
          AND status = 'confirmed'
          AND serverId IS NOT NULL
        """,
    )
    suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long>

    /**
     * issue #65 slice 4: the local Room PK of the offline-create row for
     * [clientRef], or null if none. Single-column read (no full-entity mapping)
     * used by [applyLocalCreateServerIdentity] to promote the row in place.
     */
    @Query("SELECT id FROM expenses WHERE ledgerId = :ledgerId AND clientRef = :clientRef LIMIT 1")
    suspend fun localRowIdForClientRef(ledgerId: String, clientRef: String): Long?

    @Insert
    suspend fun insert(expense: ExpenseEntity): Long

    @Insert
    suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertConfirmedStreamOffsets(offsets: List<ExpenseOffsetStreamEntity>)

    @Update
    suspend fun update(expense: ExpenseEntity)

    @Update
    suspend fun updateAll(expenses: List<ExpenseEntity>)

    @Transaction
    suspend fun upsertByServerIdForLedger(ledgerId: String, expense: ExpenseEntity): Boolean {
        require(expense.ledgerId == ledgerId) {
            "expense.ledgerId=${expense.ledgerId} does not match scope $ledgerId"
        }
        // issue #65 slice 4: this path keys on the server id, so it only handles
        // server-originated rows. An offline local create (serverId == null) is
        // written via insert() / applyLocalCreateServerIdentity, never here.
        val serverId = requireNotNull(expense.serverId) {
            "upsertByServerIdForLedger received a local-only row (serverId == null)"
        }
        val existing = findByServerId(ledgerId, serverId)
        if (existing == null) {
            insert(expense.copy(id = 0))
            return true
        } else if (expense.rowVersion >= existing.rowVersion) {
            // rowVersion monotonic guard: a slow full-list sync response must
            // not clobber a row a fresh PATCH already advanced (the server is
            // the source of truth and would self-heal next sync, but the UI
            // shows the stale snapshot until then). Same-version writes are
            // allowed — identical token means identical server payload.
            update(expense.withPreservedStreamProjection(existing).copy(id = existing.id))
            return true
        }
        return false
    }

    /** Keep the server's lifecycle version, including rejection, so older reads cannot revive the row. */
    @Transaction
    suspend fun applyServerExpense(ledgerId: String, expense: ExpenseEntity): Boolean {
        if (!upsertByServerIdForLedger(ledgerId, expense)) return false
        if (expense.status != "confirmed") deleteConfirmedStreamOffsetsForRoot(ledgerId, requireNotNull(expense.serverId))
        return true
    }

    @Transaction
    suspend fun upsertAllByServerIdForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
    ): Set<Long> {
        if (expenses.isEmpty()) return emptySet()
        require(expenses.all { it.ledgerId == ledgerId }) {
            "upsertAllByServerIdForLedger received mixed-ledger entities"
        }
        // issue #65 slice 4: server-id-keyed, so local-only rows (serverId ==
        // null) are skipped defensively — a single malformed row must not abort a
        // whole confirmed-list batch (server-fetched entities always carry one).
        val serverScoped = expenses.filter { it.serverId != null }
        if (serverScoped.isEmpty()) return emptySet()
        val existingByServerId = findByServerIds(ledgerId, serverScoped.mapNotNull { it.serverId })
            .associateBy { it.serverId }
        val inserts = mutableListOf<ExpenseEntity>()
        val updates = mutableListOf<ExpenseEntity>()
        val acceptedServerIds = mutableSetOf<Long>()
        serverScoped.forEach { expense ->
            val serverId = requireNotNull(expense.serverId)
            val existing = existingByServerId[serverId]
            if (existing == null) {
                inserts += expense.copy(id = 0)
                acceptedServerIds += serverId
            } else if (expense.rowVersion >= existing.rowVersion) {
                // Same monotonic guard as upsertByServerIdForLedger.
                updates += expense.withPreservedStreamProjection(existing).copy(id = existing.id)
                acceptedServerIds += serverId
            }
        }
        if (inserts.isNotEmpty()) insertAll(inserts)
        if (updates.isNotEmpty()) updateAll(updates)
        return acceptedServerIds
    }

    @Query("DELETE FROM expenses WHERE id = :id")
    suspend fun deleteByLocalId(id: Long)

    /**
     * issue #65 slice 4: write the server-assigned identity back onto the
     * optimistic offline-create row once its CreateExpense outbox row drains.
     * [serverEntity] is the original accepted creation response carrying its [ExpenseEntity.clientRef].
     * It establishes identity; a newer cached fact remains authoritative for money and fields.
     *
     * Resolves by clientRef and promotes the row IN PLACE (same Room PK), so the
     * domain id flips from its negative local stand-in to the real server id
     * without a list-key churn beyond the sync moment. Reconciles the race where
     * a confirmed-list sync already inserted the server row as a SEPARATE row
     * while the create was draining: drop the local-create row and refresh the
     * synced one, keeping one row and avoiding the (ledgerId, serverId)
     * unique-index clash. If the local row is gone (cache cleared), just cache
     * the canonical server row so the create isn't lost.
     */
    @Transaction
    suspend fun applyLocalCreateServerIdentity(ledgerId: String, serverEntity: ExpenseEntity) {
        require(serverEntity.ledgerId == ledgerId) {
            "serverEntity.ledgerId=${serverEntity.ledgerId} does not match scope $ledgerId"
        }
        val clientRef = requireNotNull(serverEntity.clientRef) {
            "applyLocalCreateServerIdentity requires the entity to carry its clientRef"
        }
        val serverId = requireNotNull(serverEntity.serverId) {
            "applyLocalCreateServerIdentity requires a server id from the create response"
        }
        val localId = localRowIdForClientRef(ledgerId, clientRef)
        val existingServer = findByServerId(ledgerId, serverId)
        if (localId == null && existingServer == null) {
            insert(serverEntity.copy(id = 0))
            return
        }
        if (localId != null && existingServer != null && existingServer.id != localId) {
            deleteByLocalId(localId)
        }
        val canonical = when {
            existingServer == null -> serverEntity
            existingServer.rowVersion > serverEntity.rowVersion -> existingServer
            else -> serverEntity.withPreservedStreamProjection(existingServer)
        }
        update(canonical.copy(id = existingServer?.id ?: requireNotNull(localId), clientRef = clientRef))
    }

    @Query("DELETE FROM expenses")
    suspend fun clear()

    @Query("DELETE FROM expenses WHERE ledgerId = :ledgerId")
    suspend fun clearForLedger(ledgerId: String)

    @Query("DELETE FROM expenses WHERE ledgerId = :ledgerId AND status = 'confirmed'")
    suspend fun deleteConfirmedForLedger(ledgerId: String)

    @Query(
        """
        DELETE FROM expenses
        WHERE ledgerId = :ledgerId
          AND status = 'confirmed'
          AND serverId IN (:serverIds)
        """,
    )
    suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>)

    @Query("DELETE FROM expense_offset_stream")
    suspend fun clearConfirmedStreamOffsets()

    @Query("DELETE FROM expense_offset_stream WHERE ledgerId = :ledgerId")
    suspend fun clearConfirmedStreamOffsetsForLedger(ledgerId: String)

    @Query(
        """
        DELETE FROM expense_offset_stream
        WHERE ledgerId = :ledgerId AND publicId IN (:publicIds)
        """,
    )
    suspend fun deleteConfirmedStreamOffsetsByPublicIds(
        ledgerId: String,
        publicIds: List<String>,
    )

    @Query(
        """
        DELETE FROM expense_offset_stream
        WHERE ledgerId = :ledgerId AND rootServerId = :rootServerId
        """,
    )
    suspend fun deleteConfirmedStreamOffsetsForRoot(ledgerId: String, rootServerId: Long)

    @Transaction
    suspend fun clearAllExpenseCaches() {
        clear()
        clearConfirmedStreamOffsets()
        clearStatsProjections()
        clearGoalSnapshots()
    }

    @Transaction
    suspend fun clearAllExpenseCachesForLedger(ledgerId: String) {
        clearForLedger(ledgerId)
        clearConfirmedStreamOffsetsForLedger(ledgerId)
        clearStatsProjectionsForLedger(ledgerId)
        clearGoalSnapshotsForLedger(ledgerId)
    }

    @Transaction
    suspend fun applyExpenseFactBundle(
        ledgerId: String,
        root: ExpenseEntity,
        activeOffsets: List<ExpenseOffsetStreamEntity>,
    ) {
        val rootServerId = requireNotNull(root.serverId)
        require(root.ledgerId == ledgerId && activeOffsets.all {
            it.ledgerId == ledgerId && it.rootServerId == rootServerId
        }) { "expense fact bundle crossed its ledger or root boundary" }
        if (!upsertByServerIdForLedger(ledgerId, root)) return
        deleteConfirmedStreamOffsetsForRoot(ledgerId, rootServerId)
        if (activeOffsets.isNotEmpty()) upsertConfirmedStreamOffsets(activeOffsets)
    }

    @Transaction
    suspend fun applyConfirmedSyncForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
        replaceCache: Boolean,
        // Prune eligibility snapshot, taken by the caller BEFORE the network
        // fetch; null disables pruning. A full-list response is a snapshot of
        // the server at request time — a row confirmed-and-cached WHILE the
        // (paginated) fetch was in flight is missing from that response, and
        // an unscoped prune would delete it. Restricting deletion to rows
        // that already existed pre-fetch keeps the prune to genuinely
        // server-deleted rows; anything cached mid-flight survives until the
        // next sync reconciles it.
        pruneScope: Set<Long>?,
    ) {
        if (replaceCache) {
            clearForLedger(ledgerId)
        }
        expenses.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
            upsertAllByServerIdForLedger(ledgerId, chunk)
        }
        if (pruneScope != null) {
            val remoteServerIds = expenses.mapNotNull { it.serverId }.toSet()
            val staleServerIds = confirmedServerIdsForLedger(ledgerId)
                .filter { it !in remoteServerIds && it in pruneScope }
            staleServerIds.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
                if (chunk.isNotEmpty()) {
                    deleteConfirmedByServerIds(ledgerId, chunk)
                }
            }
        }
    }

    /** Atomically applies the server-owned typed stream and returns the roots actually accepted. */
    @Transaction
    suspend fun applyConfirmedStreamSyncForLedger(
        ledgerId: String,
        roots: List<ExpenseEntity>,
        offsets: List<ExpenseOffsetStreamEntity>,
        replaceCache: Boolean,
        pruneScope: ConfirmedStreamPruneScope,
    ): Set<Long> {
        if (replaceCache) {
            clearForLedger(ledgerId)
            clearConfirmedStreamOffsetsForLedger(ledgerId)
        }
        val acceptedRootIds = mutableSetOf<Long>()
        roots.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
            acceptedRootIds += upsertAllByServerIdForLedger(ledgerId, chunk)
        }
        val acceptedOffsets = offsets.filter { it.rootServerId in acceptedRootIds }
        acceptedOffsets.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
            if (chunk.isNotEmpty()) upsertConfirmedStreamOffsets(chunk)
        }
        var staleRootIds: List<Long> = emptyList()
        if (pruneScope.rootServerIds != null) {
            val remoteServerIds = roots.mapNotNull { it.serverId }.toSet()
            staleRootIds = confirmedServerIdsForLedger(ledgerId)
                .filter { it in pruneScope.rootServerIds && it !in remoteServerIds }
            staleRootIds.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
                if (chunk.isNotEmpty()) deleteConfirmedByServerIds(ledgerId, chunk)
            }
        }
        if (pruneScope.offsetPublicIds != null) {
            val remotePublicIds = acceptedOffsets.map { it.publicId }.toSet()
            val prunableRootIds = acceptedRootIds + staleRootIds
            val stalePublicIds = getConfirmedStreamOffsets(ledgerId)
                .filter {
                    it.rootServerId in prunableRootIds &&
                        it.publicId in pruneScope.offsetPublicIds &&
                        it.publicId !in remotePublicIds
                }
                .map { it.publicId }
            stalePublicIds.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
                if (chunk.isNotEmpty()) deleteConfirmedStreamOffsetsByPublicIds(ledgerId, chunk)
            }
        }
        return acceptedRootIds
    }

    /** Only prune pending rows that were present and unchanged when the list request started. */
    @Transaction
    suspend fun applyPendingSyncForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
        pruneVersions: Map<Long, Long>,
    ) {
        require(expenses.all { it.ledgerId == ledgerId && it.status == "pending" })
        val remoteIds = expenses.mapNotNull { it.serverId }.toSet()
        getPending(ledgerId).filter { row ->
            row.serverId !in remoteIds && pruneVersions[row.serverId] == row.rowVersion
        }.forEach { deleteByLocalId(it.id) }
        expenses.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
            upsertAllByServerIdForLedger(ledgerId, chunk).forEach { acceptedId ->
                deleteConfirmedStreamOffsetsForRoot(ledgerId, acceptedId)
            }
        }
    }
}

private fun ExpenseEntity.withPreservedStreamProjection(existing: ExpenseEntity): ExpenseEntity {
    if (status != "confirmed" || streamDate != null) return this
    return copy(
        streamDate = existing.streamDate,
        streamSortTime = streamSortTime ?: existing.streamSortTime,
        streamSortId = streamSortId ?: existing.streamSortId,
        streamAmountCents = streamAmountCents ?: existing.streamAmountCents,
        lineageStatus = lineageStatus ?: existing.lineageStatus,
        lineageHomeNetCents = lineageHomeNetCents ?: existing.lineageHomeNetCents,
    )
}
