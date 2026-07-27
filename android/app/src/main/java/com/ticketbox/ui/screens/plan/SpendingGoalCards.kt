package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun SpendingGoalListCard(
    goals: List<Goal>,
    onOpenGoal: (String) -> Unit,
) {
    AppContentCard {
        goals.forEachIndexed { index, goal ->
            if (index > 0) {
                HorizontalDivider(
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
                )
            }
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
    com.ticketbox.ui.components.AppListRow(
        onClick = onClick,
        showDivider = false,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            SpendingGoalRowHeader(goal)
            Text(
                text = stringResource(
                    R.string.spending_goal_row_context,
                    displayMonthLabel(goal.month),
                    goal.category ?: stringResource(R.string.spending_goal_scope_all),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            AppProgressBar(
                fraction = goal.progress,
                tone = goal.stateTone(),
                height = AppSpacing.smallGap,
                contentDescription = stringResource(
                    R.string.spending_goal_progress_a11y,
                    goal.name,
                    goal.progressPercent,
                ),
            )
            SpendingGoalAmountSummary(goal)
        }
    }
}

@Composable
private fun SpendingGoalRowHeader(goal: Goal) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = goal.name,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        StatusPill(
            text = goal.statusText(),
            tone = goal.stateTone(),
        )
    }
}

@Composable
private fun SpendingGoalAmountSummary(goal: Goal) {
    val currency = LocalCurrencyDisplay.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        SpendingGoalAmountCell(
            label = stringResource(R.string.spending_goal_spent_label),
            value = formatDisplayAmount(goal.spentAmountCents, currency),
            modifier = Modifier.weight(1f),
        )
        SpendingGoalAmountCell(
            label = if (goal.isOverLimit) {
                stringResource(R.string.spending_goal_over_label)
            } else {
                stringResource(R.string.spending_goal_remaining_label)
            },
            value = formatDisplayAmount(kotlin.math.abs(goal.remainingAmountCents), currency),
            modifier = Modifier.weight(1f),
        )
        SpendingGoalAmountCell(
            label = stringResource(R.string.spending_goal_limit_label),
            value = formatDisplayAmount(goal.targetAmountCents, currency),
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun SpendingGoalAmountCell(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge.tabularNum(),
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
internal fun Goal.stateTone(): StateTone {
    val tokens = LocalGoalTokens.current
    val source = when (progressState) {
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
        GoalProgressState.Idle -> R.string.spending_goal_status_idle
        GoalProgressState.OnTrack -> R.string.spending_goal_status_on_track
        GoalProgressState.NearLimit -> R.string.spending_goal_status_near
        GoalProgressState.OverLimit -> R.string.spending_goal_status_over
        GoalProgressState.Archived -> R.string.spending_goal_status_archived
    },
)
