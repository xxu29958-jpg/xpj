package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
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
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.screens.plan.spendingGoalAmountText
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.debtGoalEvaluationLabelRes
import com.ticketbox.viewmodel.ReportGoalsLoadState

private data class GoalAmountLine(
    val label: String,
    val value: String,
)

@Composable
internal fun GoalsSummaryCard(
    goals: List<Goal>,
    loadState: ReportGoalsLoadState,
    modifier: Modifier = Modifier,
    onAddGoal: (() -> Unit)? = null,
) {
    val visibleGoals = remember(goals) { goalDisplayModels(goals) }
    val attentionCount = visibleGoals.count { it.priority <= 1 }
    val bodyKind = remember(loadState, visibleGoals.size) {
        goalsSummaryBodyKind(loadState = loadState, visibleGoalCount = visibleGoals.size)
    }
    val averagePercent = goalAveragePercent(visibleGoals)

    StatsInsightSurface(modifier = modifier) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            GoalsSummaryHeader(
                goalCount = visibleGoals.size,
                attentionCount = attentionCount,
                loadState = loadState,
            )
            GoalsSummaryStateSlot(kind = bodyKind)
            if (bodyKind == GoalsSummaryBodyKind.Empty && onAddGoal != null) {
                AppPrimaryButton(
                    text = stringResource(R.string.stats_reports_goals_create_action),
                    icon = Icons.Filled.Add,
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onAddGoal,
                )
            }
            if (bodyKind == GoalsSummaryBodyKind.Data) {
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
    loadState: ReportGoalsLoadState,
) {
    val goalTokens = LocalGoalTokens.current
    val status = goalsHeaderStatus(
        goalCount = goalCount,
        attentionCount = attentionCount,
        loadState = loadState,
    )
    val tone = when (status) {
        GoalsHeaderStatus.Loading -> goalTokens.idle
        GoalsHeaderStatus.Unavailable -> goalTokens.nearLimit
        GoalsHeaderStatus.Empty -> goalTokens.idle
        GoalsHeaderStatus.Attention -> goalTokens.nearLimit
        GoalsHeaderStatus.Stable -> goalTokens.onTrack
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(
                text = stringResource(R.string.stats_reports_goals_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = when (status) {
                    GoalsHeaderStatus.Loading -> stringResource(R.string.stats_reports_goals_loading_count)
                    GoalsHeaderStatus.Unavailable -> stringResource(R.string.stats_reports_goals_unavailable_count)
                    else -> stringResource(R.string.stats_reports_goals_count, goalCount)
                },
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
                    GoalsHeaderStatus.Loading -> stringResource(R.string.stats_reports_goals_reading)
                    GoalsHeaderStatus.Unavailable -> stringResource(R.string.stats_reports_goals_unavailable_badge)
                    GoalsHeaderStatus.Empty -> stringResource(R.string.stats_reports_goals_unset)
                    GoalsHeaderStatus.Attention -> stringResource(R.string.stats_reports_goals_attention, attentionCount)
                    GoalsHeaderStatus.Stable -> stringResource(R.string.stats_reports_goals_stable)
                },
                color = tone.fg,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun GoalsSummaryStateSlot(kind: GoalsSummaryBodyKind) {
    val (titleRes, bodyRes) = when (kind) {
        GoalsSummaryBodyKind.Loading -> R.string.stats_reports_goals_loading to R.string.stats_reports_goals_loading_hint
        GoalsSummaryBodyKind.Failed -> R.string.stats_reports_goals_unavailable to R.string.stats_reports_goals_unavailable_hint
        GoalsSummaryBodyKind.Empty -> R.string.stats_reports_goals_empty to R.string.stats_reports_goals_empty_hint
        GoalsSummaryBodyKind.Data -> return
    }
    AppContentStateSlot(
        state = AppContentStateSpec(
            loading = kind == GoalsSummaryBodyKind.Loading,
            hasData = false,
            copy = AppContentStateCopy(
                loadingTitle = stringResource(titleRes),
                loadingBody = stringResource(bodyRes),
                emptyText = stringResource(bodyRes),
                emptyTitle = stringResource(titleRes),
                emptyBody = stringResource(bodyRes),
            ),
            message = if (kind == GoalsSummaryBodyKind.Failed) {
                UiText.compound(listOf(UiText.res(titleRes), UiText.res(bodyRes)), " ")
            } else {
                null
            },
            messageTone = MessageTone.Danger,
            presentation = AppContentStatePresentation.Inline,
        ),
    )
}

@Composable
private fun GoalPortfolioRail(
    goalCount: Int,
    attentionCount: Int,
    averagePercent: Int?,
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
                text = averagePercent?.let { stringResource(R.string.stats_reports_goal_percent, it) }
                    ?: stringResource(R.string.spending_goal_amount_unavailable),
                color = goalTone.fg,
                style = MaterialTheme.typography.labelLarge.tabularNum(),
                fontWeight = FontWeight.SemiBold,
            )
        }
        if (averagePercent != null) AppProgressBar(
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
    val debtEvaluation = goal.debtRepayment.takeIf { goal.isDebtRepayment }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier.size(width = 4.dp, height = 38.dp).clip(RoundedCornerShape(AppRadius.pill)).background(tone.fg),
            )
            GoalPriorityTextColumn(model = model, modifier = Modifier.weight(1f))
            if (debtEvaluation != null) {
                Text(
                    text = model.progressPercent?.let { stringResource(R.string.stats_reports_goal_percent, it) }
                        ?: stringResource(R.string.spending_goal_amount_unavailable),
                    color = tone.fg,
                    style = MaterialTheme.typography.labelLarge.tabularNum(),
                    fontWeight = AppTextHierarchy.body.weight,
                    maxLines = 1,
                )
            } else {
                AppEndAlignedAmountText(
                    text = spendingGoalAmountText(goal.targetAmountCents, goal.homeCurrencyCode),
                    modifier = Modifier.weight(0.56f),
                    role = AppAmountRole.Compact,
                    color = tone.fg,
                )
            }
        }
        if (debtEvaluation == null) {
            GoalAmountRows(
                lines = listOf(
                    GoalAmountLine(
                        stringResource(R.string.stats_reports_goal_spent_label),
                        spendingGoalAmountText(goal.spentAmountCents, goal.homeCurrencyCode),
                    ),
                    GoalAmountLine(
                        stringResource(R.string.stats_reports_goal_remaining_label),
                        spendingGoalAmountText(goal.remainingAmountCents, goal.homeCurrencyCode),
                    ),
                ),
            )
        }
        GoalSummaryProgress(model, tone)
    }
}

@Composable
private fun GoalSummaryProgress(model: GoalDisplayModel, tone: StateTone) {
    val progress = model.progressFraction
    if (progress != null) {
        AppProgressBar(
            fraction = progress,
            tone = tone,
            height = AppSpacing.miniGap,
            contentDescription = stringResource(
                R.string.stats_reports_goal_progress_a11y,
                model.goal.name,
                requireNotNull(model.progressPercent),
            ),
        )
    } else {
        Text(stringResource(R.string.spending_goal_progress_unavailable),
            color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun GoalAmountRows(lines: List<GoalAmountLine>) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        lines.forEach { line ->
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = line.label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                AppEndAlignedAmountText(
                    text = line.value,
                    role = AppAmountRole.Compact,
                )
            }
        }
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
                goalContextText(model.goal),
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
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
                GoalProgressState.Unavailable -> R.string.spending_goal_amount_unavailable
                GoalProgressState.Idle -> R.string.stats_reports_goal_status_idle
            },
        )
    }
}

@Composable
private fun goalContextText(goal: Goal): String {
    val debtEvaluation = goal.debtRepayment.takeIf { goal.isDebtRepayment }
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
        )
    }
}

@Composable
private fun goalTone(model: GoalDisplayModel): StateTone {
    val goalTokens = LocalGoalTokens.current
    val debtEvaluation = model.goal.debtRepayment
    val tone = when {
        debtEvaluation?.needsReview == true || debtEvaluation?.isNotEvaluable == true -> goalTokens.nearLimit
        model.goal.progressState == GoalProgressState.OverLimit -> goalTokens.exceeded
        model.goal.progressState == GoalProgressState.NearLimit || model.progressFraction == null -> goalTokens.nearLimit
        model.goal.progressState == GoalProgressState.OnTrack -> goalTokens.onTrack
        model.goal.progressState == GoalProgressState.Archived -> goalTokens.expired
        else -> goalTokens.idle
    }
    return StateTone(tone.bg, tone.fg, tone.border)
}
