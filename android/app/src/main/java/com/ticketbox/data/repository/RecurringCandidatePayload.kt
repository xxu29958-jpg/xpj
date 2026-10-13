package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.domain.model.CurrencyCode

/** Captured adoption request; observations still belong to the server's scan. */
@JsonClass(generateAdapter = true)
data class RecurringCandidatePayload(
    val request: RecurringCandidateConfirmRequestDto,
    val timezone: String,
)

internal fun RecurringCandidatePayload.matchesOriginal(row: OutboxRow): Boolean =
    !row.idempotencyKey.isNullOrBlank() && row.targetId == "recurring_candidate:${row.idempotencyKey}" &&
        row.expectedRowVersion == 0L && timezone.isNotBlank() && request.merchant.isNotBlank() &&
        request.amountCents > 0 && request.frequency == "monthly" &&
        CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode) != null

internal fun RecurringItemDto.confirms(row: OutboxRow, payload: RecurringCandidatePayload): Boolean =
    publicId.isNotBlank() && ledgerId == row.ledgerId && rowVersion == 1L && source == "candidate" &&
        status == "active" && frequency == payload.request.frequency &&
        homeCurrencyCode == payload.request.homeCurrencyCode && baselineAmountCents == payload.request.amountCents &&
        lastAmountCents == payload.request.amountCents &&
        (payload.request.nextExpectedDate == null || nextExpectedDate == payload.request.nextExpectedDate)
