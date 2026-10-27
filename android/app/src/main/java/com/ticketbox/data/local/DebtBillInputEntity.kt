package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/** Original input and file ownership survive Outbox receipts and completed-row cleanup. */
@Entity(tableName = "debt_bill_inputs")
data class DebtBillInputEntity(
    @PrimaryKey val captureKey: String,
    val ownerKey: String,
    val ledgerId: String,
    val creationKey: String,
    val payloadJson: String,
    val draftJson: String,
    val sourceJson: String? = null,
    val parseAttemptKey: String? = null,
    val parseExpectedRowVersion: Long? = null,
    val closed: Boolean = false,
)

@Dao
interface DebtBillInputDao {
    @Query("SELECT * FROM debt_bill_inputs WHERE ownerKey = :owner AND ledgerId = :ledger ORDER BY rowid DESC")
    fun observeInputs(owner: String, ledger: String): Flow<List<DebtBillInputEntity>>

    @Query("SELECT * FROM debt_bill_inputs")
    suspend fun allInputs(): List<DebtBillInputEntity>

    @Query("SELECT * FROM debt_bill_inputs WHERE captureKey = :key")
    suspend fun input(key: String): DebtBillInputEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(input: DebtBillInputEntity)

    @Query("UPDATE debt_bill_inputs SET draftJson = :draft WHERE captureKey = :key AND closed = 0")
    suspend fun saveDraft(key: String, draft: String)

    @Query("UPDATE debt_bill_inputs SET sourceJson = :source WHERE captureKey = :key")
    suspend fun saveSource(key: String, source: String)

    @Query("UPDATE debt_bill_inputs SET parseAttemptKey = :attempt, parseExpectedRowVersion = :version WHERE captureKey = :key AND closed = 0")
    suspend fun saveParseAttempt(key: String, attempt: String, version: Long)

    @Query("UPDATE debt_bill_inputs SET closed = 1 WHERE captureKey = :key")
    suspend fun close(key: String)
}
