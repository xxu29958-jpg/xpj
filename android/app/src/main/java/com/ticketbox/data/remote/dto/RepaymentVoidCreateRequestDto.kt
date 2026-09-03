package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class RepaymentVoidCreateRequestDto(
    @param:Json(name = "repayment_public_id") val repaymentPublicId: String,
    val reason: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)
