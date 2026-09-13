package com.ticketbox.data.remote.dto

import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class RecurringCapturedCurrencyTest {
    private val moshi = Moshi.Builder().addRecurringWireAdapters().add(KotlinJsonAdapterFactory()).build()

    @Test
    fun `currencyless original commands cannot acquire a new default currency`() {
        assertFailsWith<JsonDataException> {
            moshi.adapter(RecurringItemCreateRequestDto::class.java)
                .fromJson("""{"merchant":"Subscription","baseline_amount_cents":1200}""")
        }
        assertFailsWith<JsonDataException> {
            moshi.adapter(RecurringItemUpdateRequestDto::class.java)
                .fromJson("""{"expected_row_version":1,"baseline_amount_cents":1200}""")
        }
        assertFailsWith<JsonDataException> {
            moshi.adapter(RecurringCandidateConfirmRequestDto::class.java)
                .fromJson("""{"merchant":"Subscription","amount_cents":1200}""")
        }
    }

    @Test
    fun `stored JPY intent retains its currency and exact minor amount`() {
        val adapter = moshi.adapter(RecurringItemCreateRequestDto::class.java)
        val original = requireNotNull(adapter.fromJson(
            """{"merchant":"Subscription","home_currency_code":"JPY","baseline_amount_cents":1200}""",
        ))
        val wire = adapter.toJson(original)
        assertTrue("\"home_currency_code\":\"JPY\"" in wire)
        assertTrue("\"baseline_amount_cents\":1200" in wire)
    }
}
