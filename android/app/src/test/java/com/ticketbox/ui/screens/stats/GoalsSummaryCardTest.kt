package com.ticketbox.ui.screens.stats

import com.ticketbox.viewmodel.ReportGoalsLoadState
import kotlin.test.Test
import kotlin.test.assertEquals

class GoalsSummaryCardTest {

    @Test
    fun emptyGoalSetIsNotTreatedAsStable() {
        assertEquals(
            GoalsHeaderStatus.Empty,
            goalsHeaderStatus(
                goalCount = 0,
                attentionCount = 0,
                loadState = ReportGoalsLoadState.Loaded,
            ),
        )
        assertEquals(
            GoalsHeaderStatus.Loading,
            goalsHeaderStatus(
                goalCount = 0,
                attentionCount = 0,
                loadState = ReportGoalsLoadState.Loading,
            ),
        )
        assertEquals(
            GoalsHeaderStatus.Loading,
            goalsHeaderStatus(
                goalCount = 0,
                attentionCount = 0,
                loadState = ReportGoalsLoadState.Unknown,
            ),
        )
    }

    @Test
    fun failedGoalLoadIsNotTreatedAsUnset() {
        assertEquals(
            GoalsHeaderStatus.Unavailable,
            goalsHeaderStatus(
                goalCount = 0,
                attentionCount = 0,
                loadState = ReportGoalsLoadState.Failed,
            ),
        )
        assertEquals(
            GoalsHeaderStatus.Unavailable,
            goalsHeaderStatus(
                goalCount = 2,
                attentionCount = 0,
                loadState = ReportGoalsLoadState.Failed,
            ),
        )
    }

    @Test
    fun attentionBeatsStableWhenGoalsNeedReview() {
        assertEquals(
            GoalsHeaderStatus.Attention,
            goalsHeaderStatus(
                goalCount = 3,
                attentionCount = 1,
                loadState = ReportGoalsLoadState.Loaded,
            ),
        )
    }

    @Test
    fun stableRequiresAtLeastOneGoalAndNoAttentionItems() {
        assertEquals(
            GoalsHeaderStatus.Stable,
            goalsHeaderStatus(
                goalCount = 2,
                attentionCount = 0,
                loadState = ReportGoalsLoadState.Loaded,
            ),
        )
    }
}
