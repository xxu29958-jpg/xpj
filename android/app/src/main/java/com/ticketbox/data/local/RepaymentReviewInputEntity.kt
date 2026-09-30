package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/** Human input is not a query projection. Cache cleanup must never remove it. */
@Entity(tableName = "repayment_review_inputs", primaryKeys = ["ownerKey", "ledgerId", "draftPublicId"])
data class RepaymentReviewInputEntity(
    val ownerKey: String,
    val ledgerId: String,
    val draftPublicId: String,
    val serverUrl: String,
    val sessionGeneration: String,
    val bindingRevision: String,
    val originalKey: String,
    val currency: String,
    val amountText: String,
    val debtPublicId: String? = null,
    val debtLabel: String? = null,
    val debtHomeCurrency: String? = null,
    val debtRowVersion: Long? = null,
    val submittedAction: String? = null,
)

@Dao
interface RepaymentReviewInputDao {
    @Query("SELECT * FROM repayment_review_inputs WHERE ownerKey = :owner AND ledgerId = :ledger AND draftPublicId = :draft")
    suspend fun get(owner: String, ledger: String, draft: String): RepaymentReviewInputEntity?

    @Query("SELECT * FROM repayment_review_inputs WHERE ownerKey = :owner AND ledgerId = :ledger AND draftPublicId = :draft")
    fun observe(owner: String, ledger: String, draft: String): Flow<RepaymentReviewInputEntity?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(input: RepaymentReviewInputEntity)
}
