package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class OriginalCommandReceipt(
    val operation: String,
    @param:Json(name = "expense_id") val expenseId: Long,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "accepted_at") val acceptedAt: String,
    val sha256: String? = null,
    @param:Json(name = "cleanup_request_id") val cleanupRequestId: String? = null,
    @param:Json(name = "cleanup_pending") val cleanupPending: Boolean? = null,
)
