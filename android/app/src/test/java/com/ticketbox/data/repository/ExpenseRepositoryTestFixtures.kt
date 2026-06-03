package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity

internal fun cachedConfirmedEntity(
    serverId: Long,
    publicId: String,
    merchant: String,
    ledgerId: String = "owner",
): ExpenseEntity =
    ExpenseEntity(
        ledgerId = ledgerId,
        serverId = serverId,
        publicId = publicId,
        amountCents = 1200,
        merchant = merchant,
        category = "交通",
        note = null,
        source = "缓存",
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-05-01T00:00:00Z",
        createdAt = "2026-05-01T00:00:00Z",
        confirmedAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
    )

internal fun unsupported(): Nothing = error("Unexpected API call")
