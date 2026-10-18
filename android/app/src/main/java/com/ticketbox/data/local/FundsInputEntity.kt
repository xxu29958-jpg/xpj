package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/** Unsubmitted money input and its frozen command survive process death independently of read caches. */
@Entity(tableName = "funds_inputs", primaryKeys = ["serverUrl", "ownerKey", "ledgerId"])
data class FundsInputEntity(val serverUrl: String, val ownerKey: String, val ledgerId: String,
    val originalKey: String, val inputJson: String, val commandJson: String? = null)

@Dao
interface FundsInputDao {
    @Query("SELECT * FROM funds_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger")
    suspend fun get(server: String, owner: String, ledger: String): FundsInputEntity?
    @Query("SELECT * FROM funds_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger")
    fun observe(server: String, owner: String, ledger: String): Flow<FundsInputEntity?>
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(input: FundsInputEntity)
    @Query("DELETE FROM funds_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger AND originalKey = :key")
    suspend fun remove(server: String, owner: String, ledger: String, key: String)
}
