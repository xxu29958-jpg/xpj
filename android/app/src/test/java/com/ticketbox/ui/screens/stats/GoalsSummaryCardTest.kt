package com.ticketbox.ui.screens.stats

import kotlin.test.Test
import kotlin.test.assertEquals

class GoalsSummaryCardTest {

    @Test
    fun emptyGoalSetIsNotTreatedAsStable() {
        assertEquals(
            GoalsHeaderStatus.Empty,
            goalsHeaderStatus(goalCount = 0, attentionCount = 0),
        )
    }

    @Test
    fun attentionBeatsStableWhenGoalsNeedReview() {
        assertEquals(
            GoalsHeaderStatus.Attention,
            goalsHeaderStatus(goalCount = 3, attentionCount = 1),
        )
    }

    @Test
    fun stableRequiresAtLeastOneGoalAndNoAttentionItems() {
        assertEquals(
            GoalsHeaderStatus.Stable,
            goalsHeaderStatus(goalCount = 2, attentionCount = 0),
        )
    }
}
