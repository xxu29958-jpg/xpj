package com.ticketbox.data.remote.dto

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi
import java.lang.reflect.Type

/** A captured full monetary rule can explicitly clear bounds. A keyword-only rule has no currency. */
private object CategoryRuleRequestAdapterFactory : JsonAdapter.Factory {
    override fun create(type: Type, annotations: Set<Annotation>, moshi: Moshi): JsonAdapter<*>? {
        if (type != CategoryRuleUpdateRequest::class.java || annotations.isNotEmpty()) return null
        val delegate = moshi.nextAdapter<CategoryRuleUpdateRequest>(this, type, annotations)
        return object : JsonAdapter<CategoryRuleUpdateRequest>() {
            override fun fromJson(reader: JsonReader): CategoryRuleUpdateRequest? = delegate.fromJson(reader)
            override fun toJson(writer: JsonWriter, value: CategoryRuleUpdateRequest?) {
                val adapter = if (value?.homeCurrencyCode != null) delegate.serializeNulls() else delegate
                adapter.toJson(writer, value)
            }
        }
    }
}

fun Moshi.Builder.addCategoryRuleWireAdapters(): Moshi.Builder = add(CategoryRuleRequestAdapterFactory)
