package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitInboxDto
import com.ticketbox.data.remote.dto.BillSplitSentDto
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitReceivedBill

fun BillSplitSentDto.toDomain(): BillSplitSent = BillSplitSent(
    publicId = publicId,
    status = status,
    amountCents = amountCents,
    homeCurrencyCode = homeCurrencyCode,
    merchantSnapshot = merchantSnapshot,
    categorySuggestion = categorySuggestion,
    expenseTimeSnapshot = expenseTimeSnapshot,
    expiresAt = expiresAt,
    createdAt = createdAt,
    acceptedAt = acceptedAt,
    rejectedAt = rejectedAt,
    cancelledAt = cancelledAt,
    expiredAt = expiredAt,
    receiverAccountId = receiverAccountId,
    receiverDisplayNameSnapshot = receiverDisplayNameSnapshot,
    senderExpenseId = senderExpenseId,
)

fun BillSplitInboxDto.toDomain(): BillSplitInbox = BillSplitInbox(
    publicId = publicId,
    status = status,
    amountCents = amountCents,
    homeCurrencyCode = homeCurrencyCode,
    merchantSnapshot = merchantSnapshot,
    categorySuggestion = categorySuggestion,
    expenseTimeSnapshot = expenseTimeSnapshot,
    expiresAt = expiresAt,
    createdAt = createdAt,
    acceptedAt = acceptedAt,
    rejectedAt = rejectedAt,
    cancelledAt = cancelledAt,
    expiredAt = expiredAt,
    senderAccountId = senderAccountId,
    senderDisplayName = senderDisplayName,
    receivedBill = receivedBill?.let { BillSplitReceivedBill(it.expenseId, it.ledgerId, it.ledgerName) },
)
