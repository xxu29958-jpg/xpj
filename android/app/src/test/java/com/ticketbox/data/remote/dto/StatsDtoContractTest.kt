package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class StatsDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun monthlyStatsDtoParsesTagStats() {
        val dto = requireNotNull(
            moshi.adapter(MonthlyStatsDto::class.java).fromJson(
                """
                {
                  "month": "2026-05",
                  "total_amount_cents": 15800,
                  "count": 3,
                  "by_category": [
                    {"category": "餐饮", "amount_cents": 15800, "count": 3}
                  ],
                  "by_tag": [
                    {"tag": "真香", "amount_cents": 12000, "count": 2}
                  ]
                }
                """.trimIndent(),
            ),
        )

        assertEquals("真香", dto.byTag.single().tag)
        assertEquals(12000L, dto.byTag.single().amountCents)
    }
}
