package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/** The original accepted payment identity; a receipt does not replace a current Debt query. */
@JsonClass(generateAdapter = true)
data class DebtRepaymentReceiptDto(
    @param:Json(name = "public_id") val debtPublicId: String,
    @param:Json(name = "repayment_public_id") val repaymentPublicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
)
