package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseConfirmationReceiptDto
import com.ticketbox.domain.model.ExpenseConfirmationReceipt

internal fun ExpenseConfirmationReceiptDto.toDomain(): ExpenseConfirmationReceipt = ExpenseConfirmationReceipt(
    id = id,
    publicId = publicId,
    rowVersion = rowVersion,
    factRevision = factRevision,
    status = status,
    amountCents = amountCents,
    homeCurrency = homeCurrency,
    originalCurrencyCode = originalCurrencyCode,
    originalAmountMinor = originalAmountMinor,
    exchangeRateToCny = exchangeRateToCny,
    exchangeRateDate = exchangeRateDate,
    exchangeRateSource = exchangeRateSource,
    merchant = merchant,
    category = category,
    accountingTime = accountingTime?.toDomain(),
    confirmedAt = confirmedAt,
)
