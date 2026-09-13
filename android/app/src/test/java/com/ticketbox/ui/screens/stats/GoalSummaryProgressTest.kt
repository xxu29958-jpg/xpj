package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class GoalSummaryProgressTest {
    private val known = Goal(
        publicId = "jpy", ledgerId = "owner", name = "旅行", goalType = "spending_limit",
        period = "monthly", month = "2026-09", category = null, targetAmountCents = 1200,
        spentAmountCents = 600, remainingAmountCents = 600, progressPercent = 50,
        progressState = GoalProgressState.OnTrack, status = "active", createdAt = "", updatedAt = "",
        rowVersion = 1, archivedAt = null, homeCurrencyCode = "JPY",
    )

    @Test fun unavailableGoalGetsAttentionAndPreventsAClaimedPortfolioAverage() {
        val unknown = known.copy(publicId = "missing-fx", spentAmountCents = null,
            remainingAmountCents = null, progressPercent = null, progressState = GoalProgressState.Unavailable)
        val models = goalDisplayModels(listOf(known, unknown))
        assertEquals("missing-fx", models.first().goal.publicId)
        assertEquals(0, models.first().priority)
        assertNull(models.first().progressFraction)
        assertNull(goalAveragePercent(models))
    }

    @Test fun knownProgressAndLoadedEmptyStayDistinct() {
        assertEquals(50, goalAveragePercent(goalDisplayModels(listOf(known))))
        assertNull(goalAveragePercent(emptyList()))
        assertEquals("JPY", goalDisplayModels(listOf(known)).single().goal.homeCurrencyCode)
    }
}
