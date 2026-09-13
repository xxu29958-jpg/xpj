package com.ticketbox.data.remote.dto

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import java.lang.reflect.Type

/** Explicit null means the user observed an unconfigured month. Other commands keep their wire shape. */
private object BudgetRequestAdapterFactory : JsonAdapter.Factory {
    override fun create(type: Type, annotations: Set<Annotation>, moshi: Moshi): JsonAdapter<*>? =
        if (type == BudgetMonthlyUpdateRequestDto::class.java && annotations.isEmpty()) {
            moshi.nextAdapter<BudgetMonthlyUpdateRequestDto>(this, type, annotations).serializeNulls()
        } else { null }
}

fun Moshi.Builder.addBudgetWireAdapters(): Moshi.Builder = add(BudgetRequestAdapterFactory)
