package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi

/**
 * A correction field has three wire states: absent (unchanged), a concrete
 * value, or explicit JSON null (clear). Moshi normally omits nullable values,
 * so a plain `Int?`/`String?` cannot preserve that distinction through the
 * offline outbox. These tiny carriers keep the existing backend contract
 * (`model_fields_set`) without inventing a second persistent state machine.
 */
data class CorrectionOptionalInt(
    val changed: Boolean,
    val value: Int?,
) {
    companion object {
        fun unchanged(): CorrectionOptionalInt = CorrectionOptionalInt(changed = false, value = null)
        fun changed(value: Int?): CorrectionOptionalInt = CorrectionOptionalInt(changed = true, value = value)
    }
}

data class CorrectionOptionalString(
    val changed: Boolean,
    val value: String?,
) {
    companion object {
        fun unchanged(): CorrectionOptionalString = CorrectionOptionalString(changed = false, value = null)
        fun changed(value: String?): CorrectionOptionalString = CorrectionOptionalString(changed = true, value = value)
    }
}

class CorrectionOptionalIntJsonAdapter : JsonAdapter<CorrectionOptionalInt>() {
    override fun fromJson(reader: JsonReader): CorrectionOptionalInt =
        if (reader.peek() == JsonReader.Token.NULL) {
            reader.nextNull<Unit>()
            CorrectionOptionalInt.changed(null)
        } else {
            CorrectionOptionalInt.changed(reader.nextInt())
        }

    override fun toJson(writer: JsonWriter, value: CorrectionOptionalInt?) {
        val field = requireNotNull(value)
        writeOptionalNull(writer, changed = field.changed, value = field.value) { writer.value(it) }
    }
}

class CorrectionOptionalStringJsonAdapter : JsonAdapter<CorrectionOptionalString>() {
    override fun fromJson(reader: JsonReader): CorrectionOptionalString =
        if (reader.peek() == JsonReader.Token.NULL) {
            reader.nextNull<Unit>()
            CorrectionOptionalString.changed(null)
        } else {
            CorrectionOptionalString.changed(reader.nextString())
        }

    override fun toJson(writer: JsonWriter, value: CorrectionOptionalString?) {
        val field = requireNotNull(value)
        writeOptionalNull(writer, changed = field.changed, value = field.value) { writer.value(it) }
    }
}

private inline fun <T> writeOptionalNull(
    writer: JsonWriter,
    changed: Boolean,
    value: T?,
    writeValue: (T) -> Unit,
) {
    if (value != null) {
        writeValue(value)
        return
    }
    val previous = writer.serializeNulls
    writer.serializeNulls = changed
    try {
        writer.nullValue()
    } finally {
        writer.serializeNulls = previous
    }
}

fun Moshi.Builder.addExpenseCorrectionWireAdapters(): Moshi.Builder =
    add(CorrectionOptionalInt::class.java, CorrectionOptionalIntJsonAdapter())
        .add(CorrectionOptionalString::class.java, CorrectionOptionalStringJsonAdapter())

@JsonClass(generateAdapter = true)
data class ExpenseCorrectionRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    val reason: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long? = null,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    val merchant: String? = null,
    val category: String? = null,
    val note: String? = null,
    @param:Json(name = "expense_time")
    val expenseTime: CorrectionOptionalString = CorrectionOptionalString.unchanged(),
    val tags: String? = null,
    @param:Json(name = "value_score")
    val valueScore: CorrectionOptionalInt = CorrectionOptionalInt.unchanged(),
    @param:Json(name = "regret_score")
    val regretScore: CorrectionOptionalInt = CorrectionOptionalInt.unchanged(),
    val items: List<ExpenseItemRequestDto>? = null,
    val splits: List<ExpenseSplitRequestDto>? = null,
)

data class ExpenseRevisionDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "revision_number")
    val revisionNumber: Long,
    @param:Json(name = "change_kind")
    val changeKind: String,
    val reason: String,
    @param:Json(name = "changed_fields")
    val changedFields: List<String>,
    val before: Map<String, Any?>? = null,
    val after: Map<String, Any?>,
    @param:Json(name = "actor_account_name")
    val actorAccountName: String? = null,
    @param:Json(name = "actor_device_name")
    val actorDeviceName: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
)

data class ExpenseCorrectionResponseDto(
    val expense: ExpenseDto,
    val revision: ExpenseRevisionDto,
)

data class ExpenseRevisionPageDto(
    val items: List<ExpenseRevisionDto>,
    val page: Int,
    @param:Json(name = "page_size")
    val pageSize: Int,
    val total: Int,
)

@JsonClass(generateAdapter = true)
data class ConfirmedExpenseBatchUpdateRequestDto(
    @param:Json(name = "expense_ids")
    val expenseIds: List<Long>,
    @param:Json(name = "expected_row_version_by_id")
    val expectedRowVersionById: Map<Long, Long>,
    val category: String? = null,
    val tags: String? = null,
    val reason: String,
)

data class ConfirmedExpenseBatchUpdateResponseDto(
    @param:Json(name = "requested_count")
    val requestedCount: Int,
    @param:Json(name = "updated_count")
    val updatedCount: Int,
    @param:Json(name = "skipped_not_found")
    val skippedNotFound: Int,
    @param:Json(name = "skipped_not_confirmed")
    val skippedNotConfirmed: Int,
)
