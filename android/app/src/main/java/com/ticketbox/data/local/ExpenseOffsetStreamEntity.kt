package com.ticketbox.data.local

import androidx.room.Entity
import androidx.room.Index

/** Server-owned active offset projection used by the offline confirmed stream. */
@Entity(
    tableName = "expense_offset_stream",
    primaryKeys = ["ledgerId", "publicId"],
    indices = [
        Index(value = ["ledgerId", "streamDate"]),
        Index(value = ["ledgerId", "rootServerId"]),
    ],
)
data class ExpenseOffsetStreamEntity(
    val ledgerId: String,
    val publicId: String,
    val rootServerId: Long,
    val kind: String,
    val streamDate: String,
    val streamSortTime: String,
    val streamSortId: Long,
    val streamAmountCents: Long,
    val amountCents: Long,
    val originalAmountMinor: Long,
    val originalCurrencyCode: String,
    val homeCurrencyCode: String,
    val category: String,
)
