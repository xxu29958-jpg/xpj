package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.ticketbox.data.repository.toDomain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ReportsProjectionContractTest {
    @Test fun reportProjectionPreservesCurrencyCountsAndUnknownAmountsThroughTheRealMapper() {
        val dto = requireNotNull(Moshi.Builder().build().adapter(ReportsOverviewDto::class.java).fromJson("""
            {"month":"2026-09","timezone":"Asia/Tokyo","home_currency_code":"JPY","granularity":"day",
            "total_amount_cents":null,"count":4,"previous_month":"2026-08","previous_total_amount_cents":500,"previous_count":2,
            "year_over_year_month":"2025-09","year_over_year_total_amount_cents":null,"year_over_year_count":1,
            "year_over_year_delta_amount_cents":null,"year_over_year_delta_count":3,
            "merchant_category":null,"ranking_metric":"count",
            "trend":[{"bucket":"2026-09-01","label":"09-01","amount_cents":null,"count":4}],
            "merchant_ranking":[{"merchant":"Cafe","amount_cents":null,"count":4}],
            "category_comparison":[{"category":"餐饮","amount_cents":null,"count":4,"previous_amount_cents":500,
              "previous_count":2,"delta_amount_cents":null,"delta_count":2,"year_over_year_amount_cents":null,
              "year_over_year_count":1,"year_over_year_delta_amount_cents":null,"year_over_year_delta_count":3}],
            "missing_rates":[{"source_currency_code":"USD","home_currency_code":"JPY","rate_date":"2026-09-01"},
              {"source_currency_code":null,"home_currency_code":"JPY","rate_date":null}]}
        """.trimIndent()))
        val report = dto.toDomain()
        assertEquals("JPY", report.homeCurrencyCode)
        assertEquals(4, report.count)
        assertNull(report.totalAmountCents)
        assertEquals(500L, report.previousTotalAmountCents)
        assertNull(report.trend.single().amountCents)
        assertNull(report.merchantRanking.single().amountCents)
        assertNull(report.categoryComparison.single().deltaAmountCents)
        assertNull(report.yearOverYearDeltaAmountCents)
        assertEquals("USD", report.missingRates.first().sourceCurrencyCode)
        assertNull(report.missingRates.last().rateDate)
    }
}
