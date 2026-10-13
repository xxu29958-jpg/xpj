package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/** Original user input and command receipts are retained independently of query caches and Outbox. */
@Entity(tableName = "merchant_creation_inputs", primaryKeys = ["serverUrl", "ownerKey", "ledgerId", "kind"])
data class MerchantCreationInputEntity(
    val serverUrl: String,
    val ownerKey: String,
    val ledgerId: String,
    val kind: String,
    val originalKey: String,
    val draftJson: String,
)

@Dao
interface MerchantCreationInputDao {
    @Query("SELECT * FROM merchant_creation_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger")
    suspend fun get(server: String, owner: String, ledger: String): List<MerchantCreationInputEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(input: MerchantCreationInputEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAll(inputs: List<MerchantCreationInputEntity>)

    @Query("DELETE FROM merchant_creation_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger AND kind = :kind AND originalKey = :key")
    suspend fun remove(server: String, owner: String, ledger: String, kind: String, key: String)

    @Query("DELETE FROM merchant_creation_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger AND originalKey IN (:keys)")
    suspend fun removeKeys(server: String, owner: String, ledger: String, keys: List<String>)
}
