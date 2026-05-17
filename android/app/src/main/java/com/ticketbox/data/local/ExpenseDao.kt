package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

/**
 * v0.4-alpha1 multi-ledger contract:
 *
 * Every confirmed query MUST filter by [ledgerId]. The `serverId` index stays
 * globally unique because the backend mints `Expense.id` from a single
 * autoincrement sequence — there is no overlap between ledgers — but we
 * still match on `(ledgerId, serverId)` from the DAO so a misconfigured
 * server can never cross-write a row into the wrong ledger's cache.
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
        "SELECT * FROM expenses WHERE ledgerId = :ledgerId AND serverId = :serverId LIMIT 1",
    )
    suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity?

    @Query(
        "SELECT * FROM expenses WHERE ledgerId = :ledgerId AND serverId IN (:serverIds)",
    )
    suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity>

    /**
     * Look up cached rows by serverId across *all* ledgers. Used during sync
     * upserts to absorb pre-multi-ledger ('legacy') rows into the active
     * ledger without violating the global UNIQUE(serverId) index. Backend
     * guarantees serverId is globally unique (single autoincrement), so a
     * row found here is by definition the same row.
     */
    @Query(
        "SELECT * FROM expenses WHERE serverId IN (:serverIds)",
    )
    suspend fun findAnyByServerIds(serverIds: List<Long>): List<ExpenseEntity>

    @Insert
    suspend fun insert(expense: ExpenseEntity): Long

    @Insert
    suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long>

    @Update
    suspend fun update(expense: ExpenseEntity)

    @Update
    suspend fun updateAll(expenses: List<ExpenseEntity>)

    @Transaction
    suspend fun upsertByServerIdForLedger(ledgerId: String, expense: ExpenseEntity) {
        require(expense.ledgerId == ledgerId) {
            "expense.ledgerId=${expense.ledgerId} does not match scope $ledgerId"
        }
        // Match across all ledgers; see upsertAllByServerIdForLedger.
        val existing = findAnyByServerIds(listOf(expense.serverId)).firstOrNull()
        if (existing == null) {
            insert(expense.copy(id = 0))
        } else {
            update(expense.copy(id = existing.id))
        }
    }

    @Transaction
    suspend fun upsertAllByServerIdForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
    ) {
        if (expenses.isEmpty()) return
        require(expenses.all { it.ledgerId == ledgerId }) {
            "upsertAllByServerIdForLedger received mixed-ledger entities"
        }
        // Match by serverId across all ledgers so 'legacy' rows from a v0.3
        // → v0.4 migration are re-tagged to the active ledger instead of
        // colliding with the global UNIQUE(serverId) index. Backend assigns
        // serverId from a single autoincrement, so every existing match is
        // the same logical row.
        val existingByServerId = findAnyByServerIds(expenses.map { it.serverId })
            .associateBy { it.serverId }
        val inserts = mutableListOf<ExpenseEntity>()
        val updates = mutableListOf<ExpenseEntity>()
        expenses.forEach { expense ->
            val existing = existingByServerId[expense.serverId]
            if (existing == null) {
                inserts += expense.copy(id = 0)
            } else {
                updates += expense.copy(id = existing.id)
            }
        }
        if (inserts.isNotEmpty()) insertAll(inserts)
        if (updates.isNotEmpty()) updateAll(updates)
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
          AND serverId NOT IN (:serverIds)
        """,
    )
    suspend fun deleteConfirmedNotInServerIds(ledgerId: String, serverIds: List<Long>)
}
