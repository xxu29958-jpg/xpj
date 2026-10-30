package com.ticketbox.ui.screens.plan

import com.ticketbox.domain.model.GOAL_TYPE_SPENDING_LIMIT
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.RecurringItem
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PlanStatusSummaryTest {
    @Test
    fun nextFixedPaymentIsTheEarliestActiveDueDateWithMerchantTieBreak() {
        val next = planNextFixedPayment(
            listOf(
                recurring("paused", due = "2026-10-01", status = "paused"),
                recurring("undated", due = null),
                recurring("房租", due = "2026-11-01"),
                recurring("宽带", due = "2026-10-15"),
                recurring("保险", due = "2026-10-15"),
            ),
        )

        assertEquals("保险", next?.merchant)
    }

    @Test
    fun noNextFixedPaymentWithoutAnActiveDueDate() {
        assertNull(planNextFixedPayment(listOf(recurring("undated", due = null), recurring("paused", "2026-10-01", "paused"))))
    }

    @Test
    fun goalHighlightsLeadWithGoalsThatNeedAttentionAndKeepServerOrderOtherwise() {
        val highlights = planGoalHighlights(
            listOf(
                goal("总支出", GoalProgressState.OnTrack),
                goal("餐饮", GoalProgressState.NearLimit),
                goal("旧目标", GoalProgressState.OverLimit, archived = true),
                goal("交通", GoalProgressState.Idle),
                goal("购物", GoalProgressState.OverLimit),
            ),
        )

        assertEquals(listOf("购物", "餐饮", "总支出", "交通"), highlights.map { it.name })
    }

    private fun recurring(merchant: String, due: String?, status: String = "active") = RecurringItem(
        publicId = "rec-$merchant", ledgerId = "owner", merchant = merchant, merchantKey = merchant, frequency = "monthly",
        baselineAmountCents = 100_00, lastAmountCents = 100_00, occurrenceCount = 0, lastSeenAt = null,
        nextExpectedDate = due, status = status, confidence = null, source = "manual", anomalyStatus = "normal",
        currentMonthAmountCents = null, historicalAverageAmountCents = null, amountDeltaPercent = null,
        createdAt = "2026-06-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 1L,
        pausedAt = null, archivedAt = null, nextDueDate = due, homeCurrencyCode = "CNY",
    )

    private fun goal(name: String, state: GoalProgressState, archived: Boolean = false) = Goal(
        publicId = "goal-$name", ledgerId = "owner", name = name, goalType = GOAL_TYPE_SPENDING_LIMIT,
        period = "monthly", month = "2026-10", category = null, targetAmountCents = 900_00, spentAmountCents = 600_00,
        remainingAmountCents = 300_00, progressPercent = 66, progressState = state,
        status = if (archived) "archived" else "active", createdAt = "2026-10-01T00:00:00Z",
        updatedAt = "2026-10-01T00:00:00Z", rowVersion = 1L, archivedAt = null, homeCurrencyCode = "CNY",
    )
}
