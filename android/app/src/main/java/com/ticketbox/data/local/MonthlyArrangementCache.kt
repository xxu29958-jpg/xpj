package com.ticketbox.data.local

import androidx.room.*

/** Saved server projection and unsent raw draft are separate rows; neither overwrites the other. */
@Entity(tableName = "monthly_arrangement_cache", primaryKeys = ["bindingKey", "month", "kind"])
data class MonthlyArrangementCacheEntity(val bindingKey: String, val month: String, val kind: String, val json: String)
@Dao
interface MonthlyArrangementCacheDao {
    @Query("SELECT * FROM monthly_arrangement_cache WHERE bindingKey = :bindingKey AND month = :month AND kind = :kind")
    suspend fun read(bindingKey: String, month: String, kind: String): MonthlyArrangementCacheEntity?
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun write(row: MonthlyArrangementCacheEntity)
    @Query("DELETE FROM monthly_arrangement_cache WHERE bindingKey = :bindingKey AND month = :month AND kind = 'draft'")
    suspend fun removeDraft(bindingKey: String, month: String)
}
