package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface ExpenseFactQueryCacheDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveFactSnapshot(snapshot: ExpenseFactQueryCacheEntity)

    @Query("SELECT * FROM expense_fact_query_cache WHERE bindingKey = :bindingKey AND expenseId = :expenseId AND queryKey = :queryKey")
    suspend fun factSnapshot(bindingKey: String, expenseId: Long, queryKey: String): ExpenseFactQueryCacheEntity?

    @Query("DELETE FROM expense_fact_query_cache WHERE bindingKey = :bindingKey AND expenseId = :expenseId")
    suspend fun clearFactSnapshotsForExpense(bindingKey: String, expenseId: Long)

    @Query("DELETE FROM expense_fact_query_cache WHERE bindingKey = :bindingKey")
    suspend fun clearFactSnapshotsForBinding(bindingKey: String)

    @Query("DELETE FROM expense_fact_query_cache WHERE ledgerId = :ledgerId")
    suspend fun clearFactSnapshotsForLedger(ledgerId: String)

    @Query("DELETE FROM expense_fact_query_cache")
    suspend fun clearFactSnapshots()
}
