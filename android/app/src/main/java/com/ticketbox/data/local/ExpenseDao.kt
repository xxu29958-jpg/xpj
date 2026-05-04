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

    @Insert
    suspend fun insert(expense: ExpenseEntity): Long

    @Update
    suspend fun update(expense: ExpenseEntity)

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
        expenses.forEach { upsertByServerId(it) }
    }

    @Query("DELETE FROM expenses")
    suspend fun clear()
}
