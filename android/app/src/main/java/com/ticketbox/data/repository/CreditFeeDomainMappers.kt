package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CreditFeeViewDto
import com.ticketbox.domain.model.CreditFeeView

internal fun CreditFeeViewDto.toDomain(): CreditFeeView = CreditFeeView(
    expenseId = expenseId,
    note = note,
    occurredOn = occurredOn,
    originalMinor = originalMinor,
    remainingMinor = remainingMinor,
    periodPublicId = periodPublicId,
)
