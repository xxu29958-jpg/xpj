package com.ticketbox.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import com.ticketbox.domain.model.FxContract

@Entity(
    tableName = "expenses",
    indices = [
        Index(value = ["ledgerId", "serverId"], unique = true),
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
    val imageDeletedAt: String? = null,
    val thumbnailDeletedAt: String? = null,
    val imageHash: String?,
    val rawText: String?,
    val confidence: Double? = null,
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
    // ADR-0041: optimistic-concurrency version mirrored from the server.
    // server_default 1 on the backend; cached rows get DEFAULT 1 on the
    // v10→v11 migration and the real value on the next sync refresh.
    @ColumnInfo(defaultValue = "1")
    val rowVersion: Long,
)
