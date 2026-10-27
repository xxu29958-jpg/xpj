package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ReferenceRateDto
import com.ticketbox.data.remote.dto.ReferenceRateRequestDto
import com.ticketbox.data.remote.dto.ReferenceRatesDto
import com.ticketbox.domain.model.ReferenceRate
import com.ticketbox.domain.model.ReferenceRateRequest
import com.ticketbox.domain.model.ReferenceRates

internal fun ReferenceRateDto.toDomain(): ReferenceRate = ReferenceRate(
    currencyCode = currencyCode,
    homeCurrencyCode = homeCurrencyCode,
    rateDate = rateDate,
    rateToHome = rateToHome,
    source = source,
    fetchedAt = fetchedAt,
    verifiedThrough = verifiedThrough,
)

internal fun ReferenceRateRequestDto.toDomain(): ReferenceRateRequest = ReferenceRateRequest(
    homeCurrencyCode = homeCurrencyCode,
    currencyCode = currencyCode,
    rateDate = rateDate,
)

internal fun ReferenceRateRequest.toDto(): ReferenceRateRequestDto = ReferenceRateRequestDto(
    homeCurrencyCode = homeCurrencyCode,
    currencyCode = currencyCode,
    rateDate = rateDate,
)

internal fun ReferenceRatesDto.toDomain(): ReferenceRates = ReferenceRates(
    provider = provider,
    autoEnabled = autoEnabled,
    syncState = syncState,
    requestedDate = requestedDate,
    effective = effective?.toDomain(),
    items = items.map { it.toDomain() },
)
