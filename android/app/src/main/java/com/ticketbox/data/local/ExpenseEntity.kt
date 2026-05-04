package com.ticketbox.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "expenses",
    indices = [Index(value = ["serverId"], unique = true)],
)
data class ExpenseEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val serverId: Long,
    val amountCents: Long?,
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
