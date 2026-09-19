package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class UndatedPeriodProjectionTest {
    private val moshi = Moshi.Builder().build()

    @Test
    fun undatedCountStaysDistinctFromFxGapsAndAbsentLegacyMetadata() {
        val adapter = moshi.adapter(MonthlyStatsDto::class.java)
        val json = """{"home_currency_code":"CNY","month":"2026-09","total_amount_cents":null,
            "count":0,"by_category":[],"missing_rates":[],"undated_expense_count":2}"""
        val current = requireNotNull(adapter.fromJson(json)).toDomain()
        assertEquals(2, current.undatedExpenseCount)
        assertNull(current.totalAmountCents)
        assertTrue(current.missingRates.isEmpty())
        val oldJson = json.replace(",\"undated_expense_count\":2", "")
        assertNull(requireNotNull(adapter.fromJson(oldJson)).toDomain().undatedExpenseCount)
    }

    @Test
    fun unknownPeriodComparisonCountsDecodeAndRemainUnavailable() {
        val json = """{"month":"2026-09","timezone":"Asia/Shanghai","granularity":"day",
            "total_amount_cents":null,"count":0,"previous_month":"2026-08","previous_total_amount_cents":null,
            "previous_count":0,"year_over_year_month":"2025-09","year_over_year_total_amount_cents":null,
            "year_over_year_count":0,"year_over_year_delta_amount_cents":null,"year_over_year_delta_count":null,
            "merchant_category":null,"ranking_metric":"amount","trend":[],"merchant_ranking":[],
            "category_comparison":[],"home_currency_code":"CNY","missing_rates":[],"undated_expense_count":1}"""
        val adapter = moshi.adapter(ReportsOverviewDto::class.java)
        val result = requireNotNull(adapter.fromJson(json)).toDomain()
        assertNull(result.yearOverYearDeltaCount)
        assertNull(result.totalAmountCents)
        assertEquals(1, result.undatedExpenseCount)
        assertTrue(result.missingRates.isEmpty())
    }
}
