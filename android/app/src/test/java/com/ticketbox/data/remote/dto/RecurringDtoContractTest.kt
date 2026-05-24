package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class RecurringDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun recurringItemsParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(RecurringItemListResponseDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "recurring-1",
                      "ledger_id": "owner",
                      "merchant": "ChatGPT Plus",
                      "merchant_key": "chatgpt plus",
                      "frequency": "monthly",
                      "baseline_amount_cents": 20000,
                      "last_amount_cents": 20000,
                      "occurrence_count": 3,
                      "last_seen_at": "2026-05-05T12:00:00Z",
                      "next_expected_date": "2026-06-05",
                      "status": "active",
                      "confidence": "high",
                      "source": "candidate",
                      "anomaly_status": "higher_than_average",
                      "current_month_amount_cents": 28000,
                      "historical_average_amount_cents": 20000,
                      "amount_delta_percent": 40,
                      "created_at": "2026-05-13T00:00:00Z",
                      "updated_at": "2026-05-13T00:00:00Z",
                      "paused_at": null,
                      "archived_at": null
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        val item = dto.items.single()
        assertEquals("recurring-1", item.publicId)
        assertEquals("owner", item.ledgerId)
        assertEquals("ChatGPT Plus", item.merchant)
        assertEquals(20000L, item.baselineAmountCents)
        assertEquals("2026-06-05", item.nextExpectedDate)
        assertEquals("active", item.status)
        assertEquals("higher_than_average", item.anomalyStatus)
        assertEquals(28000L, item.currentMonthAmountCents)
        assertEquals(40, item.amountDeltaPercent)
    }
}
