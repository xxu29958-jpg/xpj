package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentFactDto
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtRepaymentVoid

internal fun RepaymentFactDto.toDomain() = DebtRepayment(
    publicId, amountCents, paidAt, createdAt, status,
    voidFact?.let { DebtRepaymentVoid(it.publicId, it.reason, it.createdAt) },
    originalCurrencyCode, originalAmountMinor, exchangeRateToCny, exchangeRateDate, exchangeRateSource,
)
