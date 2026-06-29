package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class ReportsDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun reportsOverviewParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(ReportsOverviewDto::class.java).fromJson(
                """
                {
                  "month": "2026-05",
                  "timezone": "Asia/Shanghai",
                  "granularity": "day",
                  "total_amount_cents": 4200,
                  "count": 3,
                  "previous_month": "2026-04",
                  "previous_total_amount_cents": 500,
                  "previous_count": 1,
                  "year_over_year_month": "2025-05",
                  "year_over_year_total_amount_cents": 1800,
                  "year_over_year_count": 2,
                  "year_over_year_delta_amount_cents": 2400,
                  "year_over_year_delta_count": 1,
                  "merchant_category": "餐饮",
                  "ranking_metric": "count",
                  "trend": [
                    {"bucket": "2026-05-01", "label": "05-01", "amount_cents": 1200, "count": 1}
                  ],
                  "merchant_ranking": [
                    {"merchant": "星巴克", "amount_cents": 2000, "count": 2}
                  ],
                  "category_comparison": [
                    {
                      "category": "餐饮",
                      "amount_cents": 2000,
                      "count": 2,
                      "previous_amount_cents": 500,
                      "previous_count": 1,
                      "delta_amount_cents": 1500,
                      "delta_count": 1,
                      "year_over_year_amount_cents": 1800,
                      "year_over_year_count": 1,
                      "year_over_year_delta_amount_cents": 200,
                      "year_over_year_delta_count": 1
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        assertEquals("2026-05", dto.month)
        assertEquals("餐饮", dto.merchantCategory)
        assertEquals("count", dto.rankingMetric)
        assertEquals("2025-05", dto.yearOverYearMonth)
        assertEquals(2400L, dto.yearOverYearDeltaAmountCents)
        assertEquals(1200L, dto.trend.single().amountCents)
        assertEquals("星巴克", dto.merchantRanking.single().merchant)
        assertEquals(1500L, dto.categoryComparison.single().deltaAmountCents)
        assertEquals(200L, dto.categoryComparison.single().yearOverYearDeltaAmountCents)
    }
}
