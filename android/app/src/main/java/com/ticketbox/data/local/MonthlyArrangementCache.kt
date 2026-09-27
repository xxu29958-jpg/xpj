package com.ticketbox.data.local

import androidx.room.*
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types

/** Saved server projection and unsent raw draft are separate rows; neither overwrites the other. */
@Entity(tableName = "monthly_arrangement_cache", primaryKeys = ["bindingKey", "month", "kind"])
data class MonthlyArrangementCacheEntity(val bindingKey: String, val month: String, val kind: String, val json: String)
@Dao
interface MonthlyArrangementCacheDao {
    @Query("SELECT * FROM monthly_arrangement_cache WHERE bindingKey = :bindingKey AND month = :month AND kind = :kind")
    suspend fun read(bindingKey: String, month: String, kind: String): MonthlyArrangementCacheEntity?
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun write(row: MonthlyArrangementCacheEntity)
    @Query("DELETE FROM monthly_arrangement_cache WHERE bindingKey = :bindingKey AND month = :month AND kind = 'draft' AND json = :expectedJson")
    suspend fun consumeDraft(bindingKey: String, month: String, expectedJson: String)
}

private val monthlyBindingFields = Moshi.Builder().build().adapter<Map<String, String>>(
    Types.newParameterizedType(Map::class.java, String::class.java, String::class.java))

internal fun monthlyArrangementCacheLedgerId(bindingKey: String): String? =
    monthlyBindingFields.fromJson(bindingKey)?.get("ledgerId")
