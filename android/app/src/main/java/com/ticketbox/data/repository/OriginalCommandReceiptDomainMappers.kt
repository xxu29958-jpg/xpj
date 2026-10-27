package com.ticketbox.data.repository

internal fun com.ticketbox.data.remote.dto.OriginalCommandReceiptDto.toDomain() = com.ticketbox.domain.model.OriginalCommandReceipt(
    operation = operation,
    expenseId = expenseId,
    publicId = publicId,
    rowVersion = rowVersion,
    acceptedAt = acceptedAt,
    sha256 = sha256,
    cleanupRequestId = cleanupRequestId,
    cleanupPending = cleanupPending,
)
