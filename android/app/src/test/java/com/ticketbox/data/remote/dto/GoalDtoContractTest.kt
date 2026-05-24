package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class GoalDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun goalsParseCurrentServerShapeAndSerializeRequests() {
        val dto = requireNotNull(
            moshi.adapter(GoalListResponseDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "goal-1",
                      "ledger_id": "owner",
                      "name": "本月餐饮",
                      "goal_type": "spending_limit",
                      "period": "monthly",
                      "month": "2026-05",
                      "category": "餐饮",
                      "target_amount_cents": 80000,
                      "spent_amount_cents": 64000,
                      "remaining_amount_cents": 16000,
                      "progress_percent": 80,
                      "progress_state": "near_limit",
                      "status": "active",
                      "created_at": "2026-05-13T00:00:00Z",
                      "updated_at": "2026-05-13T00:00:00Z",
                      "archived_at": null
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val createJson = moshi.adapter(GoalCreateRequestDto::class.java).toJson(
            GoalCreateRequestDto(
                name = "本月餐饮",
                month = "2026-05",
                category = "餐饮",
                targetAmountCents = 80000,
            ),
        )
        val updateJson = moshi.adapter(GoalUpdateRequestDto::class.java).toJson(
            GoalUpdateRequestDto(targetAmountCents = 90000),
        )

        val goal = dto.items.single()
        assertEquals("goal-1", goal.publicId)
        assertEquals("owner", goal.ledgerId)
        assertEquals("near_limit", goal.progressState)
        assertEquals(80, goal.progressPercent)
        assertEquals(
            """{"name":"本月餐饮","month":"2026-05","target_amount_cents":80000,"category":"餐饮","goal_type":"spending_limit","period":"monthly"}""",
            createJson,
        )
        assertEquals("""{"target_amount_cents":90000}""", updateJson)
    }
}
