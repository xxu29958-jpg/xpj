package com.ticketbox.ui.screens.stats

internal enum class GoalsHeaderStatus {
    Empty,
    Attention,
    Stable,
}

internal fun goalsHeaderStatus(goalCount: Int, attentionCount: Int): GoalsHeaderStatus = when {
    goalCount <= 0 -> GoalsHeaderStatus.Empty
    attentionCount > 0 -> GoalsHeaderStatus.Attention
    else -> GoalsHeaderStatus.Stable
}
