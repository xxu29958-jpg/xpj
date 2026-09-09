package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalProgressState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class SpendingGoalCurrencyMappingTest {
    private val dto = GoalDto(
        publicId = "jpy-goal", ledgerId = "owner", name = "旅行限额", goalType = "spending_limit",
        period = "monthly", month = "2026-09", category = null, targetAmountCents = 1200,
        spentAmountCents = null, remainingAmountCents = null, progressPercent = null,
        progressState = "unavailable", status = "active", createdAt = "2026-09-01T00:00:00Z",
        updatedAt = "2026-09-01T00:00:00Z", rowVersion = 1, archivedAt = null,
        homeCurrencyCode = "JPY",
    )

    @Test fun missingConversionRemainsUnknownAlongsideTheCapturedTarget() {
        val goal = dto.toDomain()
        assertEquals("JPY", goal.homeCurrencyCode)
        assertEquals(1200L, goal.targetAmountCents)
        assertNull(goal.spentAmountCents)
        assertNull(goal.remainingAmountCents)
        assertNull(goal.progressPercent)
        assertNull(goal.progress)
        assertEquals(GoalProgressState.Unavailable, goal.progressState)
    }

    @Test fun legacyCurrencyIsNotInferredAndTheRawTargetIsKept() {
        val goal = dto.copy(homeCurrencyCode = null).toDomain()
        assertNull(goal.homeCurrencyCode)
        assertEquals(1200L, goal.targetAmountCents)
        assertNull(goal.progress)
    }

    @Test fun createCarriesTheCurrencyThatParsedTheUsersAmount() {
        val request = GoalDraft("旅行限额", "2026-09", 1200, homeCurrencyCode = "JPY").toRequest()
        assertEquals("JPY", request.homeCurrencyCode)
        assertEquals(1200L, request.targetAmountCents)
    }
}
