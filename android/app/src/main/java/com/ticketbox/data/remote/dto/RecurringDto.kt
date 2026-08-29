package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi

/**
 * PATCH needs three states for the reminder date: absent (leave it alone), a
 * concrete ISO date, or explicit JSON null (clear it). Keeping that distinction
 * in the wire DTO lets the existing outbox replay the same user intent without
 * inventing another persisted recurring-item state.
 */
data class RecurringOptionalDate(
    val changed: Boolean,
    val value: String?,
) {
    companion object {
        fun unchanged(): RecurringOptionalDate = RecurringOptionalDate(changed = false, value = null)
        fun changed(value: String?): RecurringOptionalDate = RecurringOptionalDate(changed = true, value = value)
    }
}

class RecurringOptionalDateJsonAdapter : JsonAdapter<RecurringOptionalDate>() {
    override fun fromJson(reader: JsonReader): RecurringOptionalDate =
        if (reader.peek() == JsonReader.Token.NULL) {
            reader.nextNull<Unit>()
            RecurringOptionalDate.changed(null)
        } else {
            RecurringOptionalDate.changed(reader.nextString())
        }

    override fun toJson(writer: JsonWriter, value: RecurringOptionalDate?) {
        val field = requireNotNull(value)
        if (field.value != null) {
            writer.value(field.value)
            return
        }
        val previous = writer.serializeNulls
        writer.serializeNulls = field.changed
        try {
            writer.nullValue()
        } finally {
            writer.serializeNulls = previous
        }
    }
}

fun Moshi.Builder.addRecurringWireAdapters(): Moshi.Builder =
    add(RecurringOptionalDate::class.java, RecurringOptionalDateJsonAdapter())

@JsonClass(generateAdapter = true)
data class RecurringItemCreateRequestDto(
    val merchant: String,
    @param:Json(name = "baseline_amount_cents")
    val baselineAmountCents: Long,
    @param:Json(name = "next_expected_date")
    val nextExpectedDate: String? = null,
)

@JsonClass(generateAdapter = true)
data class RecurringItemUpdateRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    val merchant: String? = null,
    @param:Json(name = "baseline_amount_cents")
    val baselineAmountCents: Long? = null,
    @param:Json(name = "next_expected_date")
    val nextExpectedDate: RecurringOptionalDate = RecurringOptionalDate.unchanged(),
)

data class RecurringCandidateConfirmRequestDto(
    val merchant: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val frequency: String = "monthly",
    @param:Json(name = "next_expected_date")
    val nextExpectedDate: String? = null,
)

data class RecurringItemDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val merchant: String,
    @param:Json(name = "merchant_key")
    val merchantKey: String,
    val frequency: String,
    @param:Json(name = "baseline_amount_cents")
    val baselineAmountCents: Long,
    @param:Json(name = "last_amount_cents")
    val lastAmountCents: Long,
    @param:Json(name = "occurrence_count")
    val occurrenceCount: Int,
    @param:Json(name = "last_seen_at")
    val lastSeenAt: String?,
    @param:Json(name = "next_expected_date")
    val nextExpectedDate: String?,
    val status: String,
    val confidence: String?,
    val source: String,
    @param:Json(name = "anomaly_status")
    val anomalyStatus: String = "none",
    @param:Json(name = "current_month_amount_cents")
    val currentMonthAmountCents: Long? = null,
    @param:Json(name = "historical_average_amount_cents")
    val historicalAverageAmountCents: Long? = null,
    @param:Json(name = "amount_delta_percent")
    val amountDeltaPercent: Int? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "paused_at")
    val pausedAt: String?,
    @param:Json(name = "archived_at")
    val archivedAt: String?,
)

// ADR-0038 PR-A: OCC token body for pause/resume. Mirrors the backend
// RecurringItemTokenRequest — the recurring screen sends the item's last-seen
// updatedAt so a stale toggle (e.g. another device already paused) gets a 409
// instead of silently re-flipping. Same shape as ExpenseStateTokenRequest.
data class RecurringItemTokenRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

data class RecurringItemListResponseDto(
    val items: List<RecurringItemDto>,
)
