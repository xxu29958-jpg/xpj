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
     * [serverEntity] is the server's canonical row (``serverId`` + ``publicId`` +
     * ``rowVersion`` set) carrying the original [ExpenseEntity.clientRef].
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
        if (localId == null) {
            upsertByServerIdForLedger(ledgerId, serverEntity)
            return
        }
        val existingServer = findByServerId(ledgerId, serverId)
        if (existingServer != null && existingServer.id != localId) {
            deleteByLocalId(localId)
            update(serverEntity.copy(id = existingServer.id))
        } else {
            update(serverEntity.copy(id = localId))
        }
    }

    @Query("DELETE FROM expenses")
    suspend fun clear()

    @Query("DELETE FROM expenses WHERE ledgerId = :ledgerId")
    suspend fun clearForLedger(ledgerId: String)

    @Query("DELETE FROM expenses WHERE ledgerId = :ledgerId AND status = 'confirmed'")
    suspend fun deleteConfirmedForLedger(ledgerId: String)

    @Query("DELETE FROM expenses WHERE ledgerId = :ledgerId AND status = 'pending'")
    suspend fun deletePendingForLedger(ledgerId: String)

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
    }

    @Transaction
    suspend fun clearAllExpenseCachesForLedger(ledgerId: String) {
        clearForLedger(ledgerId)
        clearConfirmedStreamOffsetsForLedger(ledgerId)
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

    /** Atomically applies the server-owned typed confirmed stream projection. */
    @Transaction
    suspend fun applyConfirmedStreamSyncForLedger(
        ledgerId: String,
        roots: List<ExpenseEntity>,
        offsets: List<ExpenseOffsetStreamEntity>,
        replaceCache: Boolean,
        pruneScope: ConfirmedStreamPruneScope,
    ) {
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
    }

    /**
     * issue #64 A3：pending 列表本地优先读的写回路。pending 取自一次性的
     * `GET /api/expenses/pending`（非分页、单次原子调用，见
     * ExpenseRepositoryCore.syncPendingFromService），故整张列表一并到达 —
     * 直接 wholesale-replace（清掉本账本所有 pending → 重新插入响应里的 pending）
     * 就是正确口径，无需 applyConfirmedSyncForLedger 那套 pruneScope/分页快照：
     * confirmed 走分页、且 cacheIfConfirmed 会在分页 in-flight 时旁路写缓存，所以
     * 才要 prune 来分辨「服务端删了」vs「分页期间新缓存的」；pending 两者都不存在
     * （没有第二条写 pending 行的路径）。
     *
     * 只删 status='pending'（deletePendingForLedger，不是 clearForLedger）——
     * confirmed 缓存与 pending 缓存共表，wholesale 清整张表会连带清掉 LedgerScreen
     * 的 confirmed 缓存。
     */
    @Transaction
    suspend fun applyPendingSyncForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
    ) {
        deletePendingForLedger(ledgerId)
        expenses.chunked(SQLITE_BINDING_CHUNK_SIZE).forEach { chunk ->
            upsertAllByServerIdForLedger(ledgerId, chunk)
        }
    }
}

private fun ExpenseEntity.withPreservedStreamProjection(existing: ExpenseEntity): ExpenseEntity {
    if (streamDate != null) return this
    return copy(
        streamDate = existing.streamDate,
        streamSortTime = streamSortTime ?: existing.streamSortTime,
        streamSortId = streamSortId ?: existing.streamSortId,
        streamAmountCents = streamAmountCents ?: existing.streamAmountCents,
        lineageStatus = lineageStatus ?: existing.lineageStatus,
        lineageHomeNetCents = lineageHomeNetCents ?: existing.lineageHomeNetCents,
    )
}
