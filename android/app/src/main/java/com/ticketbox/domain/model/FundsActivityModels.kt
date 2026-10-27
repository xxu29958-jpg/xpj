package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ActivityCorrectionPart(
    @param:Json(name = "account_public_id") val accountPublicId: String,
    @param:Json(name = "account_row_version") val accountRowVersion: Long,
    @param:Json(name = "account_name") val accountName: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "amount_minor") val amountMinor: Long,
)
