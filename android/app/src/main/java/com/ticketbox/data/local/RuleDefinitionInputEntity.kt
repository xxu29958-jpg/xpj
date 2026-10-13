package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/** Unsubmitted input, separate from saved rule facts and the delivery Outbox. */
@Entity(tableName = "rule_definition_inputs", primaryKeys = ["serverUrl", "ownerKey", "ledgerId", "slot"])
data class RuleDefinitionInputEntity(
    val serverUrl: String,
    val ownerKey: String,
    val ledgerId: String,
    val slot: String,
    val originalKey: String,
    val inputJson: String,
)

@Dao
interface RuleDefinitionInputDao {
    @Query("SELECT * FROM rule_definition_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger")
    suspend fun get(server: String, owner: String, ledger: String): List<RuleDefinitionInputEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(input: RuleDefinitionInputEntity)

    @Query("DELETE FROM rule_definition_inputs WHERE serverUrl = :server AND ownerKey = :owner AND ledgerId = :ledger AND slot = :slot AND inputJson = :original")
    suspend fun consume(server: String, owner: String, ledger: String, slot: String, original: String): Int
}
