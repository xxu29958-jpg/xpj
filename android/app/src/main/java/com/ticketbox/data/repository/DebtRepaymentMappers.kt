package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentFactListDto
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtRepaymentPage
import com.ticketbox.domain.model.DebtRepaymentVoid

internal fun RepaymentFactListDto.toDomain() = DebtRepaymentPage(
    debtPublicId = debtPublicId,
    homeCurrencyCode = homeCurrencyCode,
    items = items.map { payment ->
        DebtRepayment(
            publicId = payment.publicId,
            amountCents = payment.amountCents,
            paidAt = payment.paidAt,
            createdAt = payment.createdAt,
            status = payment.status,
            voidFact = payment.voidFact?.let { DebtRepaymentVoid(it.publicId, it.reason, it.createdAt) },
            originalCurrencyCode = payment.originalCurrencyCode,
            originalAmountMinor = payment.originalAmountMinor,
        )
    },
    page = page,
    pageSize = pageSize,
    total = total,
)
