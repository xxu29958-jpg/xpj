package com.ticketbox.data.repository

internal fun com.ticketbox.data.remote.dto.AmountConversionDto.toDomain() = com.ticketbox.domain.model.AmountConversion(
    convertedAmount = convertedAmount,
    references = references.map { it.toDomain() },
)
