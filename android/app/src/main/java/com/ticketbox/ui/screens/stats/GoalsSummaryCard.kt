package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.debtGoalEvaluationLabelRes
import kotlin.math.roundToInt

private data class GoalDisplayModel(
    val goal: Goal,
    val progressFraction: Float,
    val progressPercent: Int,
    val priority: Int,
)

@Composable
internal fun GoalsSummaryCard(
    goals: List<Goal>,
    modifier: Modifier = Modifier,
) {
    val visibleGoals = remember(goals) { goalDisplayModels(goals) }
    val attentionCount = visibleGoals.count { it.priority <= 1 }
    val averagePercent = if (visibleGoals.isEmpty()) {
        0
    } else {
        visibleGoals.map { it.progressPercent.coerceIn(0, 100) }.average().roundToInt()
    }

    StatsInsightSurface(modifier = modifier) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            GoalsSummaryHeader(goalCount = visibleGoals.size, attentionCount = attentionCount)
            if (visibleGoals.isEmpty()) {
                GoalsSummaryEmpty()
            } else {
                GoalPortfolioRail(
                    goalCount = visibleGoals.size,
                    attentionCount = attentionCount,
                    averagePercent = averagePercent,
                )
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                    visibleGoals.take(4).forEachIndexed { index, model ->
                        if (index > 0) {
                            HorizontalDivider(
                                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle),
                            )
                        }
                        GoalPriorityRow(model = model)
                    }
                }
            }
        }
    }
}

@Composable
private fun GoalsSummaryHeader(
    goalCount: Int,
    attentionCount: Int,
) {
    val goalTokens = LocalGoalTokens.current
    val status = goalsHeaderStatus(goalCount = goalCount, attentionCount = attentionCount)
    val tone = when (status) {
        GoalsHeaderStatus.Empty -> goalTokens.idle
        GoalsHeaderStatus.Attention -> goalTokens.nearLimit
        GoalsHeaderStatus.Stable -> goalTokens.onTrack
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(R.string.stats_reports_goals_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.stats_reports_goals_count, goalCount),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
            )
        }
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(tone.bg)
                .size(width = 94.dp, height = 34.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = when (status) {
                    GoalsHeaderStatus.Empty -> stringResource(R.string.stats_reports_goals_unset)
                    GoalsHeaderStatus.Attention -> stringResource(R.string.stats_reports_goals_attention, attentionCount)
                    GoalsHeaderStatus.Stable -> stringResource(R.string.stats_reports_goals_stable)
                },
                color = tone.fg,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun GoalsSummaryEmpty() {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(
            text = stringResource(R.string.stats_reports_goals_empty),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.body.weight,
        )
        Text(
            text = stringResource(R.string.stats_reports_goals_empty_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun GoalPortfolioRail(
    goalCount: Int,
    attentionCount: Int,
    averagePercent: Int,
) {
    val goalTokens = LocalGoalTokens.current
    val goalTone = if (attentionCount > 0) goalTokens.nearLimit else goalTokens.onTrack
    val progressTone = StateTone(goalTone.bg, goalTone.fg, goalTone.border)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.stats_reports_goals_average_label),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
            )
            Text(
                text = stringResource(R.string.stats_reports_goal_percent, averagePercent.coerceAtLeast(0)),
                color = goalTone.fg,
                style = MaterialTheme.typography.labelLarge.tabularNum(),
                fontWeight = FontWeight.SemiBold,
            )
        }
        AppProgressBar(
            fraction = averagePercent / 100f,
            tone = progressTone,
            height = AppSpacing.smallGap,
            contentDescription = stringResource(
                R.string.stats_reports_goals_progress_a11y,
                goalCount,
                averagePercent,
            ),
        )
    }
}

@Composable
private fun GoalPriorityRow(model: GoalDisplayModel) {
    val goal = model.goal
    val tone = goalTone(model)
    val currencyDisplay = LocalCurrencyDisplay.current
    val debtEvaluation = goal.debtRepayment.takeIf { goal.isDebtRepayment }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            GoalStatusMark(tone = tone)
            GoalPriorityTextColumn(model = model, modifier = Modifier.weight(1f))
            Text(
                text = if (debtEvaluation != null) {
                    stringResource(R.string.stats_reports_goal_percent, model.progressPercent.coerceAtLeast(0))
                } else {
                    formatDisplayAmount(goal.targetAmountCents, currencyDisplay)
                },
                color = tone.fg,
                style = MaterialTheme.typography.labelLarge.tabularNum(),
                fontWeight = AppTextHierarchy.body.weight,
                maxLines = 1,
            )
        }
        AppProgressBar(
            fraction = model.progressFraction,
            tone = tone,
            height = AppSpacing.miniGap,
            contentDescription = stringResource(
                R.string.stats_reports_goal_progress_a11y,
                goal.name,
                model.progressPercent,
            ),
        )
    }
}

@Composable
private fun GoalPriorityTextColumn(
    model: GoalDisplayModel,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = model.goal.name,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(
                R.string.stats_reports_goal_meta_line,
                goalStatusText(model.goal),
                goalMetaText(model.goal),
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun GoalStatusMark(tone: StateTone) {
    Box(
        modifier = Modifier
            .size(width = 4.dp, height = 38.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(tone.fg),
    )
}

@Composable
private fun goalStatusText(goal: Goal): String {
    val debtEvaluation = goal.debtRepayment.takeIf { goal.isDebtRepayment }
    return if (debtEvaluation != null) {
        stringResource(debtGoalEvaluationLabelRes(debtEvaluation.evaluationState))
    } else {
        stringResource(
            when (goal.progressState) {
                GoalProgressState.OverLimit -> R.string.stats_reports_goal_status_over
                GoalProgressState.NearLimit -> R.string.stats_reports_goal_status_near
                GoalProgressState.OnTrack -> R.string.stats_reports_goal_status_on_track
                GoalProgressState.Archived -> R.string.stats_reports_goal_status_archived
                GoalProgressState.Idle -> R.string.stats_reports_goal_status_idle
            },
        )
    }
}

@Composable
private fun goalMetaText(goal: Goal): String {
    val debtEvaluation = goal.debtRepayment.takeIf { goal.isDebtRepayment }
    val currencyDisplay = LocalCurrencyDisplay.current
    val goalTypeText = when {
        goal.isDebtRepayment -> stringResource(R.string.stats_reports_goal_type_debt)
        goal.isSpendingLimit -> stringResource(R.string.stats_reports_goal_type_spending)
        else -> stringResource(R.string.stats_reports_goal_type_unknown)
    }
    return if (debtEvaluation != null) {
        stringResource(
            R.string.stats_reports_goal_debt_progress,
            goalTypeText,
            debtEvaluation.clearedCount,
            debtEvaluation.totalCount,
        )
    } else {
        stringResource(
            R.string.stats_reports_goal_progress,
            goalTypeText,
            goal.category ?: stringResource(R.string.stats_reports_goal_total),
            formatDisplayAmount(goal.spentAmountCents, currencyDisplay),
            formatDisplayAmount(goal.remainingAmountCents, currencyDisplay),
        )
    }
}

private fun goalDisplayModels(goals: List<Goal>): List<GoalDisplayModel> =
    goals
        .filterNot { it.isArchived }
        .map { goal ->
            val debtEvaluation = goal.debtRepayment
            val progressFraction = if (goal.isDebtRepayment && debtEvaluation != null) {
                debtEvaluation.planFraction
            } else {
                goal.progress
            }.coerceIn(0f, 1f)
            val progressPercent = if (goal.isDebtRepayment && debtEvaluation != null) {
                (progressFraction * 100).roundToInt()
            } else {
                goal.progressPercent
            }
            val priority = when {
                debtEvaluation?.needsReview == true || debtEvaluation?.isNotEvaluable == true -> 0
                goal.progressState == GoalProgressState.OverLimit -> 0
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

@Composable
private fun goalTone(model: GoalDisplayModel): StateTone {
    val goalTokens = LocalGoalTokens.current
    val debtEvaluation = model.goal.debtRepayment
    val tone = when {
        debtEvaluation?.needsReview == true || debtEvaluation?.isNotEvaluable == true -> goalTokens.nearLimit
        model.goal.progressState == GoalProgressState.OverLimit -> goalTokens.exceeded
        model.goal.progressState == GoalProgressState.NearLimit -> goalTokens.nearLimit
        model.goal.progressState == GoalProgressState.OnTrack -> goalTokens.onTrack
        model.goal.progressState == GoalProgressState.Archived -> goalTokens.expired
        else -> goalTokens.idle
    }
    return StateTone(tone.bg, tone.fg, tone.border)
}
