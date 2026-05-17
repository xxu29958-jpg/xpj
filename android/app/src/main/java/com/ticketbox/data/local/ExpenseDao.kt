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
        "SELECT * FROM expenses WHERE ledgerId = :ledgerId AND serverId = :serverId LIMIT 1",
    )
    suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity?

    @Query(
        "SELECT * FROM expenses WHERE ledgerId = :ledgerId AND serverId IN (:serverIds)",
    )
    suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity>

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
        val existing = findByServerId(ledgerId, expense.serverId)
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
        val existingByServerId = findByServerIds(ledgerId, expenses.map { it.serverId })
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
