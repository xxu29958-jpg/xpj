package com.ticketbox.ui.screens.stats

import com.ticketbox.viewmodel.ReportGoalsLoadState

internal enum class GoalsHeaderStatus {
    Loading,
    Unavailable,
    Empty,
    Attention,
    Stable,
}

internal fun goalsHeaderStatus(
    goalCount: Int,
    attentionCount: Int,
    loadState: ReportGoalsLoadState,
): GoalsHeaderStatus = when {
    loadState == ReportGoalsLoadState.Failed -> GoalsHeaderStatus.Unavailable
    loadState != ReportGoalsLoadState.Loaded -> GoalsHeaderStatus.Loading
    goalCount <= 0 -> GoalsHeaderStatus.Empty
    attentionCount > 0 -> GoalsHeaderStatus.Attention
    else -> GoalsHeaderStatus.Stable
}
