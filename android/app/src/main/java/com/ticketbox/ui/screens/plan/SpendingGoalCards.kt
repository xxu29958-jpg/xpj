package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.StateTone

@Composable
internal fun SpendingGoalListCard(
    goals: List<Goal>,
    onOpenGoal: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)) {
        goals.forEach { goal ->
            SpendingGoalRow(
                goal = goal,
                onClick = { onOpenGoal(goal.publicId) },
            )
        }
    }
}

@Composable
private fun SpendingGoalRow(
    goal: Goal,
    onClick: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(
            text = goal.name,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(
                R.string.spending_goal_row_context,
                displayMonthLabel(goal.month),
                goal.category ?: stringResource(R.string.spending_goal_scope_all),
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        SpendingGoalSummaryCard(goal)
        com.ticketbox.ui.components.AccountingDateNotice(goal.undatedExpenseCount)
    }
}

@Composable
internal fun SpendingGoalSummaryCard(goal: Goal) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Surface(shape = RoundedCornerShape(AppRadius.hero), color = LocalThemeVisuals.current.surfaceApricot,
            modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(AppSpacing.screenHorizontal), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                AppAdaptiveContentActionRow(
                    style = AppAdaptiveContentActionStyle(compactAction = true),
                    content = { Text(stringResource(if (goal.isOverLimit) R.string.spending_goal_over_label else R.string.spending_goal_remaining_label),
                        style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant) },
                    action = { StatusPill(text = goal.statusText(), tone = goal.stateTone()) },
                )
                AppAmountText(
                    text = spendingGoalAmountText(goal.remainingAmountCents?.let { kotlin.math.abs(it) }, goal.homeCurrencyCode),
                    role = AppAmountRole.Hero,
                    color = if (goal.isOverLimit) goal.stateTone().fg else MaterialTheme.colorScheme.onSurface,
                )
                SpendingGoalAmountSummary(goal)
            }
        }
        SpendingGoalProgress(goal, showPercent = true)
    }
}

@Composable
private fun SpendingGoalAmountSummary(goal: Goal) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        SpendingGoalAmountCell(
            label = stringResource(R.string.spending_goal_spent_label),
            value = spendingGoalAmountText(goal.spentAmountCents, goal.homeCurrencyCode),
        )
        SpendingGoalAmountCell(
            label = stringResource(R.string.spending_goal_limit_label),
            value = spendingGoalAmountText(goal.targetAmountCents, goal.homeCurrencyCode),
        )
    }
}

@Composable
private fun SpendingGoalAmountCell(
    label: String,
    value: String,
    modifier: Modifier = Modifier.widthIn(min = 128.dp),
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
        AppAmountText(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            role = AppAmountRole.Compact,
        )
    }
}

@Composable
internal fun Goal.stateTone(): StateTone {
    val tokens = LocalGoalTokens.current
    val source = when (progressState) {
        GoalProgressState.Unavailable -> tokens.nearLimit
        GoalProgressState.Idle -> tokens.idle
        GoalProgressState.OnTrack -> tokens.onTrack
        GoalProgressState.NearLimit -> tokens.nearLimit
        GoalProgressState.OverLimit -> tokens.exceeded
        GoalProgressState.Archived -> tokens.expired
    }
    return StateTone(source.bg, source.fg, source.border)
}

@Composable
internal fun Goal.statusText(): String = stringResource(
    when (progressState) {
        GoalProgressState.Unavailable -> R.string.spending_goal_amount_unavailable
        GoalProgressState.Idle -> R.string.spending_goal_status_idle
        GoalProgressState.OnTrack -> R.string.spending_goal_status_on_track
        GoalProgressState.NearLimit -> R.string.spending_goal_status_near
        GoalProgressState.OverLimit -> R.string.spending_goal_status_over
        GoalProgressState.Archived -> R.string.spending_goal_status_archived
    },
)
