package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseConfirmationReceiptDto
import com.ticketbox.data.remote.dto.ExpenseDto

/** The fixture captures acceptance once; later current reads may carry different financial facts. */
internal fun ExpenseDto.withConfirmationReceipt(): ExpenseDto = copy(
    confirmationReceipt = ExpenseConfirmationReceiptDto(
        id = id, publicId = requireNotNull(publicId), rowVersion = rowVersion, factRevision = factRevision,
        status = status, amountCents = requireNotNull(amountCents), homeCurrency = requireNotNull(homeCurrency),
        originalCurrencyCode = requireNotNull(originalCurrencyCode), originalAmountMinor = requireNotNull(originalAmountMinor),
        exchangeRateToCny = exchangeRateToCny, exchangeRateDate = exchangeRateDate, exchangeRateSource = exchangeRateSource,
        merchant = merchant, category = category, accountingTime = accountingTime, confirmedAt = confirmedAt,
    ),
)
