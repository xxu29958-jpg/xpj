package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AmountConversion(
    @param:Json(name = "converted_amount") val convertedAmount: String?,
    val references: List<ReferenceRate> = emptyList(),
)
