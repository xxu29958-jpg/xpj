package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseSplitDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun expenseSplitsParsesCurrentServerShapeAndSerializesReplace() {
        val dto = requireNotNull(
            moshi.adapter(ExpenseSplitsResponseDto::class.java).fromJson(
                """
                {
                  "expense_id": 1,
                  "parent_amount_cents": 10000,
                  "splits_total_amount_cents": 9000,
                  "mismatch_cents": 1000,
                  "splits": [
                    {
                      "public_id": "split-1",
                      "position": 0,
                      "member_id": 12,
                      "account_name": "我",
                      "role": "owner",
                      "amount_cents": 6000,
                      "note": "我出大头",
                      "disabled_at": null,
                      "created_at": "2026-05-03T04:20:00Z",
                      "updated_at": "2026-05-03T04:20:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(ExpenseSplitReplaceRequestDto::class.java).toJson(
            ExpenseSplitReplaceRequestDto(
                splits = listOf(
                    ExpenseSplitRequestDto(
                        memberId = 12,
                        amountCents = 6000,
                        note = "我出大头",
                    ),
                ),
            ),
        )

        val split = dto.splits.single()
        assertEquals("split-1", split.publicId)
        assertEquals(1000L, dto.mismatchCents)
        assertEquals("owner", split.role)
        assertEquals(
            """{"splits":[{"member_id":12,"amount_cents":6000,"note":"我出大头"}]}""",
            requestJson,
        )
    }
}
