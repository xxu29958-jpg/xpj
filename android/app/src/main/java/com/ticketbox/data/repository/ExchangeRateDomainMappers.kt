package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import com.ticketbox.domain.model.ExchangeRate
import com.ticketbox.domain.model.ExchangeRateRequest

internal fun ExchangeRateDto.toDomain(): ExchangeRate = ExchangeRate(
    publicId = publicId,
    currencyCode = currencyCode,
    homeCurrencyCode = homeCurrencyCode,
    rateDate = rateDate,
    rateToHome = rateToHome,
    source = source,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
)

internal fun ExchangeRateRequestDto.toDomain(): ExchangeRateRequest = ExchangeRateRequest(
    currencyCode = currencyCode,
    homeCurrencyCode = homeCurrencyCode,
    rateDate = rateDate,
    rateToHome = rateToHome,
    source = source,
    expectedRowVersion = expectedRowVersion,
)

internal fun ExchangeRateRequest.toDto(): ExchangeRateRequestDto = ExchangeRateRequestDto(
    currencyCode = currencyCode,
    homeCurrencyCode = homeCurrencyCode,
    rateDate = rateDate,
    rateToHome = rateToHome,
    source = source,
    expectedRowVersion = expectedRowVersion,
)
