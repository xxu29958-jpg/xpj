package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.repository.ManualRatePayload
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ManualRateDtoContractTest {
    @Test fun generatedAdaptersPreserveOriginalPairDateDecimalAndOcc() {
        val graph = OutboxAdapterGraph()
        val original = ManualRatePayload(1, "2026-09", "original-rate",
            ExchangeRateRequestDto("JPY", "USD", "2026-09-02", "0.0069", "manual", 4))
        val json = graph.manualRateAdapter.toJson(original)
        assertTrue(json.contains("\"home_currency_code\":\"USD\""))
        assertTrue(json.contains("\"rate_to_cny\":\"0.0069\""))
        assertTrue(json.contains("\"expected_row_version\":4"))
        assertEquals(original, graph.manualRateAdapter.fromJson(json))
    }

    @Test fun missingFxAndUnknownOriginalFactsRemainNullableWithNoZeroSubstitution() {
        val json = """{"month":"2026-09","home_currency_code":"JPY","breakdown":{
          "monthly_income_cents":1000,"fixed_expenses_cents":null,"spent_amount_cents":null,
          "savings_target_cents":0,"reserved_buffer_cents":0,"discretionary_cents":null},
          "missing_rates":[{"source_currency_code":null,"home_currency_code":"JPY","rate_date":null}]}"""
        val dto = requireNotNull(Moshi.Builder().build().adapter(BudgetAdviceInputsDto::class.java).fromJson(json))
        assertNull(dto.breakdown.spentAmountCents)
        assertNull(dto.breakdown.discretionaryCents)
        assertNull(dto.missingRates.single().sourceCurrencyCode)
        assertNull(dto.missingRates.single().rateDate)
        assertFalse(dto.readyForAdvice)
    }
}
