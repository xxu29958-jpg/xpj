package com.ticketbox.data.repository

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/** Queue-only payload: root affinity stays in targetId; route identity stays here. */
@JsonClass(generateAdapter = true)
data class ExpenseOffsetVoidOutboxPayload(
    @param:Json(name = "offset_public_id")
    val offsetPublicId: String,
    @param:Json(name = "void_reason")
    val voidReason: String,
)
