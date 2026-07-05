package com.ticketbox.ui.screens.stats

import com.ticketbox.viewmodel.ReportGoalsLoadState

internal enum class GoalsSummaryBodyKind {
    Loading,
    Failed,
    Empty,
    Data,
}

internal fun goalsSummaryBodyKind(
    loadState: ReportGoalsLoadState,
    visibleGoalCount: Int,
): GoalsSummaryBodyKind = when {
    loadState == ReportGoalsLoadState.Failed -> GoalsSummaryBodyKind.Failed
    loadState != ReportGoalsLoadState.Loaded -> GoalsSummaryBodyKind.Loading
    visibleGoalCount <= 0 -> GoalsSummaryBodyKind.Empty
    else -> GoalsSummaryBodyKind.Data
}
