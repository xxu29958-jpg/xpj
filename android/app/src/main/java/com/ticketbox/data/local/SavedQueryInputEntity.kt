package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/** Original query commands and receipts, never cached financial results. */
@Entity(tableName = "saved_query_inputs", primaryKeys = ["serverUrl", "ownerKey", "ledgerId", "slot"])
data class SavedQueryInputEntity(
    val serverUrl: String,
    val ownerKey: String,
    val ledgerId: String,
    val slot: String,
    val inputJson: String,
)

@Dao
interface SavedQueryInputDao {
    @Query("SELECT * FROM saved_query_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger")
    suspend fun get(server: String, owner: String, ledger: String): List<SavedQueryInputEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(input: SavedQueryInputEntity)

    @Query("DELETE FROM saved_query_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger AND slot = :slot AND inputJson = :original")
    suspend fun consume(server: String, owner: String, ledger: String, slot: String, original: String): Int
}
