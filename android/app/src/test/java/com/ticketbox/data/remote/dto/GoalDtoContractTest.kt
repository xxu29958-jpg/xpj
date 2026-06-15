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
                      "row_version": 1,
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
            GoalUpdateRequestDto(
                expectedRowVersion = 1L,
                targetAmountCents = 90000,
            ),
        )

        val goal = dto.items.single()
        assertEquals("goal-1", goal.publicId)
        assertEquals("owner", goal.ledgerId)
        assertEquals("near_limit", goal.progressState)
        assertEquals(80, goal.progressPercent)
        assertEquals(
            """{"name":"本月餐饮","goal_type":"spending_limit","period":"monthly","month":"2026-05","target_amount_cents":80000,"category":"餐饮"}""",
            createJson,
        )
        assertEquals(
            """{"expected_row_version":1,"target_amount_cents":90000}""",
            updateJson,
        )
    }

    @Test
    fun debtGoalCreateRequestSerializesDebtShape() {
        // ADR-0049 §6 (slice 8b): the debt-goal create wire body — goal_type=debt_repayment +
        // debt_public_ids, with month/target/category omitted (the backend 422s a debt goal
        // carrying them). Moshi serializes in constructor order and drops nulls.
        val debtCreateJson = moshi.adapter(GoalCreateRequestDto::class.java).toJson(
            GoalCreateRequestDto(
                name = "还清欠款",
                goalType = "debt_repayment",
                debtPublicIds = listOf("debt-a", "debt-b"),
            ),
        )
        assertEquals(
            """{"name":"还清欠款","goal_type":"debt_repayment","period":"monthly","debt_public_ids":["debt-a","debt-b"]}""",
            debtCreateJson,
        )
    }
}
