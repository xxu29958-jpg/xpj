package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Goal

internal data class DebtGoalListSummary(
    val activeGoalCount: Int,
    val achievedGoalCount: Int,
    val reviewGoalCount: Int,
    val linkedDebtCount: Int,
    val openDebtCount: Int,
    val loadingWithoutData: Boolean,
)

internal fun debtGoalListSummary(
    goals: List<Goal>,
    isLoading: Boolean,
): DebtGoalListSummary {
    val activeGoals = goals.filter { goal -> !goal.isArchived && goal.isDebtRepayment }
    val evaluations = activeGoals.mapNotNull { goal -> goal.debtRepayment }
    return DebtGoalListSummary(
        activeGoalCount = activeGoals.size,
        achievedGoalCount = evaluations.count { evaluation -> evaluation.isAchieved },
        reviewGoalCount = evaluations.count { evaluation -> evaluation.needsReview || evaluation.isNotEvaluable },
        linkedDebtCount = evaluations.sumOf { evaluation -> evaluation.totalCount },
        openDebtCount = evaluations.sumOf { evaluation -> evaluation.remainingCount },
        loadingWithoutData = isLoading && activeGoals.isEmpty(),
    )
}
