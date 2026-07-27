package com.ticketbox.data.repository

import com.ticketbox.domain.model.GoalUpdate
import kotlin.test.Test
import kotlin.test.assertEquals

class SpendingGoalUpdateMappingTest {
    @Test
    fun blankCategoryIsPreservedSoPatchCanClearTheScope() {
        val request = GoalUpdate(
            expectedRowVersion = 4L,
            category = "  ",
        ).toRequest()

        assertEquals("", request.category)
    }
}
