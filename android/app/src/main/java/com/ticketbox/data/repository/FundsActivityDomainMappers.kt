package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ActivityCorrectionPartDto
import com.ticketbox.domain.model.ActivityCorrectionPart

internal fun ActivityCorrectionPartDto.toDomain(): ActivityCorrectionPart = ActivityCorrectionPart(
    accountPublicId = accountPublicId,
    accountRowVersion = accountRowVersion,
    accountName = accountName,
    currencyCode = currencyCode,
    amountMinor = amountMinor,
)

internal fun com.ticketbox.domain.model.ActivityCorrectionPart.toDto() = com.ticketbox.data.remote.dto.ActivityCorrectionPartDto(
    accountPublicId = accountPublicId, accountRowVersion = accountRowVersion,
    accountName = accountName, currencyCode = currencyCode, amountMinor = amountMinor,
)
