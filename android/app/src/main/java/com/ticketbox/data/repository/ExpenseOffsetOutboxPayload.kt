package com.ticketbox.data.repository

import com.squareup.moshi.Json
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import java.io.IOException

/** A zero-normalized legacy request cannot prove the parent snapshot that defined its money. */
internal fun JsonAdapter<ExpenseOffsetCreateRequestDto>.readSupportedOffsetCreate(row: OutboxRow): ExpenseOffsetCreateRequestDto? {
    if (row.type != PendingMutationType.CreateExpenseOffset || row.expectedRowVersion <= 0 || row.idempotencyKey.isNullOrBlank()) return null
    return try {
        fromJson(row.payloadJson)?.takeIf { it.expectedRowVersion == row.expectedRowVersion }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }
}

/** Queue-only payload: root affinity stays in targetId; route identity stays here. */
@JsonClass(generateAdapter = true)
data class ExpenseOffsetVoidOutboxPayload(
    @param:Json(name = "offset_public_id")
    val offsetPublicId: String,
    @param:Json(name = "void_reason")
    val voidReason: String,
)
