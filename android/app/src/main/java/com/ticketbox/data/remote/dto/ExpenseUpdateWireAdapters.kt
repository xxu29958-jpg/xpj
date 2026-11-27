package com.ticketbox.data.remote.dto

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi
import okio.Buffer
import java.lang.reflect.Type

private fun hasExplicitNullOriginalAmount(reader: JsonReader): Boolean {
    var explicitNull = false
    reader.peekJson().use { peek ->
        if (peek.peek() != JsonReader.Token.BEGIN_OBJECT) return false
        peek.beginObject()
        while (peek.hasNext()) {
            if (peek.nextName() == "original_amount" && peek.peek() == JsonReader.Token.NULL) {
                explicitNull = true
                peek.nextNull<Unit>()
            } else {
                peek.skipValue()
            }
        }
        peek.endObject()
    }
    return explicitNull
}

/**
 * Preserves explicit ``"original_amount": null`` clears on [ExpenseUpdateRequest]
 * while keeping untouched fields omitted for backend ``exclude_unset`` semantics.
 */
private object ExpenseUpdateRequestAdapterFactory : JsonAdapter.Factory {
    override fun create(type: Type, annotations: Set<Annotation>, moshi: Moshi): JsonAdapter<*>? {
        if (type != ExpenseUpdateRequest::class.java || annotations.isNotEmpty()) return null
        val delegate = moshi.nextAdapter<ExpenseUpdateRequest>(this, type, annotations)
        return object : JsonAdapter<ExpenseUpdateRequest>() {
            override fun fromJson(reader: JsonReader): ExpenseUpdateRequest? {
                if (reader.peek() == JsonReader.Token.NULL) return reader.nextNull()
                val explicitClear = hasExplicitNullOriginalAmount(reader)
                val parsed = delegate.fromJson(reader) ?: return null
                return if (explicitClear && parsed.originalAmount == null) {
                    parsed.copy(clearOriginalAmount = true)
                } else {
                    parsed
                }
            }

            override fun toJson(writer: JsonWriter, value: ExpenseUpdateRequest?) {
                if (value == null) {
                    writer.nullValue()
                    return
                }
                if (!value.clearOriginalAmount || value.originalAmount != null) {
                    delegate.toJson(writer, value)
                    return
                }
                val raw = delegate.toJson(value)
                val injected = if (raw == "{}") {
                    """{"original_amount":null}"""
                } else {
                    raw.dropLast(1) + ""","original_amount":null}"""
                }
                writer.value(Buffer().writeUtf8(injected))
            }
        }
    }
}

fun Moshi.Builder.addExpenseUpdateWireAdapters(): Moshi.Builder =
    add(ExpenseUpdateRequestAdapterFactory)
