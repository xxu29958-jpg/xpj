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

    @Test
    fun lifestyleStatsDtoParsesValueAndRegretRankings() {
        val dto = requireNotNull(
            moshi.adapter(LifestyleStatsDto::class.java)
                .fromJson(lifestyleStatsWithRankingsJson),
        )

        assertEquals("真香年费", dto.bestValueExpenses.single().merchant)
        assertEquals(5, dto.bestValueExpenses.single().valueScore)
        assertEquals("后悔桌搭", dto.mostRegrettedExpenses.single().merchant)
        assertEquals(5, dto.mostRegrettedExpenses.single().regretScore)
    }
}

private val lifestyleStatsWithRankingsJson = """
{
  "month": "2026-05",
  "ai_subscription_amount_cents": 29800,
  "digital_amount_cents": 8800,
  "max_expense": null,
  "recent_7_days_amount_cents": 38600,
  "frequent_merchants": [],
  "best_value_expenses": [
    {
      "id": 42,
      "public_id": "expense_42",
      "amount_cents": 29800,
      "merchant": "真香年费",
      "category": "AI订阅",
      "note": null,
      "source": "手动记账",
      "image_path": null,
      "thumbnail_path": null,
      "image_hash": null,
      "raw_text": null,
      "confidence": null,
      "duplicate_status": "unique",
      "duplicate_of_id": null,
      "duplicate_reason": null,
      "tags": null,
      "value_score": 5,
      "regret_score": 1,
      "status": "confirmed",
      "expense_time": "2026-05-03T10:00:00Z",
      "created_at": "2026-05-03T10:01:00Z",
      "updated_at": "2026-05-03T10:01:00Z",
      "row_version": 1,
      "confirmed_at": "2026-05-03T10:01:00Z",
      "rejected_at": null
    }
  ],
  "most_regretted_expenses": [
    {
      "id": 43,
      "public_id": "expense_43",
      "amount_cents": 8800,
      "merchant": "后悔桌搭",
      "category": "数码",
      "note": null,
      "source": "手动记账",
      "image_path": null,
      "thumbnail_path": null,
      "image_hash": null,
      "raw_text": null,
      "confidence": null,
      "duplicate_status": "unique",
      "duplicate_of_id": null,
      "duplicate_reason": null,
      "tags": null,
      "value_score": 1,
      "regret_score": 5,
      "status": "confirmed",
      "expense_time": "2026-05-05T10:00:00Z",
      "created_at": "2026-05-05T10:01:00Z",
      "updated_at": "2026-05-05T10:01:00Z",
      "row_version": 1,
      "confirmed_at": "2026-05-05T10:01:00Z",
      "rejected_at": null
    }
  ]
}
""".trimIndent()
