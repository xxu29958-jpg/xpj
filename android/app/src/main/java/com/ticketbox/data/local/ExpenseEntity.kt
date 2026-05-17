package com.ticketbox.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import com.ticketbox.domain.model.FxContract

@Entity(
    tableName = "expenses",
    indices = [
        Index(value = ["serverId"], unique = true),
        Index(value = ["publicId"], unique = true),
        Index(value = ["status", "expenseTime"]),
        Index(value = ["status", "confirmedAt"]),
        Index(value = ["status", "createdAt"]),
        Index(value = ["ledgerId"]),
    ],
)
data class ExpenseEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val ledgerId: String,
    val serverId: Long,
    val publicId: String,
    val amountCents: Long?,
    val homeCurrencyCode: String = FxContract.HomeCurrency.storageKey,
    val originalCurrencyCode: String = FxContract.HomeCurrency.storageKey,
    val originalAmountMinor: Long? = null,
    val exchangeRateToCny: String? = null,
    val exchangeRateDate: String? = null,
    val exchangeRateSource: String? = null,
    val fxStatus: String = FxContract.StatusReady,
    val merchant: String?,
    val category: String,
    val note: String?,
    val source: String,
    val thumbnailPath: String?,
    val imageHash: String?,
    val rawText: String?,
    val duplicateStatus: String,
    val duplicateOfId: Long?,
    val duplicateReason: String?,
    val tags: String?,
    val valueScore: Int?,
    val regretScore: Int?,
    val status: String,
    val expenseTime: String?,
    val createdAt: String,
    val confirmedAt: String?,
    val updatedAt: String?,
)
