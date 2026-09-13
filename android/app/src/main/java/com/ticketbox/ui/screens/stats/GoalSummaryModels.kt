package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import kotlin.math.roundToInt

internal data class GoalDisplayModel(
    val goal: Goal,
    val progressFraction: Float?,
    val progressPercent: Int?,
    val priority: Int,
)

internal fun goalAveragePercent(models: List<GoalDisplayModel>): Int? {
    if (models.isEmpty() || models.any { it.progressPercent == null }) return null
    return models.map { requireNotNull(it.progressPercent).coerceIn(0, 100) }.average().roundToInt()
}

internal fun goalDisplayModels(goals: List<Goal>): List<GoalDisplayModel> =
    goals
        .filterNot { it.isArchived }
        .map { goal ->
            val debtEvaluation = goal.debtRepayment
            val progressFraction = if (goal.isDebtRepayment && debtEvaluation != null) {
                debtEvaluation.planFraction
            } else {
                goal.progress
            }?.coerceIn(0f, 1f)
            val progressPercent = if (goal.isDebtRepayment && debtEvaluation != null) {
                progressFraction?.let { (it * 100).roundToInt() }
            } else {
                goal.progressPercent
            }
            val priority = when {
                debtEvaluation?.needsReview == true || debtEvaluation?.isNotEvaluable == true -> 0
                goal.progressState == GoalProgressState.OverLimit || progressPercent == null -> 0
                goal.progressState == GoalProgressState.NearLimit -> 1
                goal.progressState == GoalProgressState.Idle -> 3
                else -> 2
            }
            GoalDisplayModel(
                goal = goal,
                progressFraction = progressFraction,
                progressPercent = progressPercent,
                priority = priority,
            )
        }
        .sortedWith(
            compareBy<GoalDisplayModel> { it.priority }
                .thenByDescending { it.progressPercent }
                .thenBy { it.goal.name },
        )

