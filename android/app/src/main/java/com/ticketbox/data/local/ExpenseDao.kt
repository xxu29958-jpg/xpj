package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface ExpenseDao {
    @Query(
        """
        SELECT * FROM expenses
        WHERE status = 'confirmed'
        ORDER BY COALESCE(expenseTime, confirmedAt, createdAt) DESC
        """,
    )
    fun observeConfirmed(): Flow<List<ExpenseEntity>>

    @Query("SELECT * FROM expenses WHERE status = 'confirmed' ORDER BY COALESCE(expenseTime, confirmedAt, createdAt) DESC")
    suspend fun getConfirmed(): List<ExpenseEntity>

    @Query("SELECT * FROM expenses WHERE serverId = :serverId LIMIT 1")
    suspend fun findByServerId(serverId: Long): ExpenseEntity?

    @Query("SELECT * FROM expenses WHERE serverId IN (:serverIds)")
    suspend fun findByServerIds(serverIds: List<Long>): List<ExpenseEntity>

    @Insert
    suspend fun insert(expense: ExpenseEntity): Long

    @Insert
    suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long>

    @Update
    suspend fun update(expense: ExpenseEntity)

    @Update
    suspend fun updateAll(expenses: List<ExpenseEntity>)

    @Transaction
    suspend fun upsertByServerId(expense: ExpenseEntity) {
        val existing = findByServerId(expense.serverId)
        if (existing == null) {
            insert(expense.copy(id = 0))
        } else {
            update(expense.copy(id = existing.id))
        }
    }

    @Transaction
    suspend fun upsertAllByServerId(expenses: List<ExpenseEntity>) {
        if (expenses.isEmpty()) return

        val existingByServerId = findByServerIds(expenses.map { it.serverId }).associateBy { it.serverId }
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
}
