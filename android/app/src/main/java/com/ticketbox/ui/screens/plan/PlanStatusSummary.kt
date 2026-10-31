package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.recurring.recurringItemMeta
import com.ticketbox.ui.screens.recurring.recurringNextDateText
import com.ticketbox.ui.screens.recurring.recurringRecordedAmountText
import com.ticketbox.viewmodel.RecurringUiState
import com.ticketbox.viewmodel.SpendingGoalsUiState

internal object PlanStatusTestTags {
    const val NextPayment = "plan_status_next_payment"
    const val Goals = "plan_status_goals"
}

private const val PLAN_STATUS_GOAL_LIMIT = 2

/** 下一笔固定支出：active 且有下次日期中最早的一笔（同日按商户名），与固定支出页「即将」同一排序。 */
internal fun planNextFixedPayment(items: List<RecurringItem>): RecurringItem? =
    items.filter { it.status == "active" && it.nextDueDate != null }
        .minWithOrNull(compareBy<RecurringItem> { it.nextDueDate }.thenBy { it.merchant })

/** 状态读数先列已超限、接近上限的目标；其余保持服务端顺序（总目标在前）。 */
internal fun planGoalHighlights(goals: List<Goal>): List<Goal> =
    goals.filterNot { it.isArchived }.sortedBy {
        when (it.progressState) {
            GoalProgressState.OverLimit -> 0
            GoalProgressState.NearLimit -> 1
            else -> 2
        }
    }

/**
 * P6：计划首页在预算之后先给状态——下一笔固定支出与本月消费目标，再列入口。
 * 只读屏幕已持有的固定支出列表与当前账本月的消费目标读取，不另算金额；每行进入对应页面。
 */
@Composable
internal fun PlanStatusCard(
    recurring: RecurringUiState,
    goals: SpendingGoalsUiState,
    onOpenRecurring: () -> Unit,
    onOpenSpendingGoal: () -> Unit,
) {
    AppPaperCard {
        Column(modifier = Modifier.fillMaxWidth()) {
            PlanStatusRow(
                label = stringResource(R.string.plan_status_next_payment_label),
                testTag = PlanStatusTestTags.NextPayment,
                onClick = onOpenRecurring,
            ) { PlanNextPaymentContent(recurring) }
            HorizontalDivider(
                modifier = Modifier.padding(horizontal = AppSpacing.cardPadding),
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft),
            )
            PlanStatusRow(
                label = stringResource(R.string.plan_status_goals_label),
                testTag = PlanStatusTestTags.Goals,
                onClick = onOpenSpendingGoal,
            ) { PlanGoalsContent(goals) }
        }
    }
}

@Composable
private fun PlanStatusRow(
    label: String,
    testTag: String,
    onClick: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(testTag)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = AppSpacing.cardPadding, vertical = AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                text = label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge,
            )
            content()
        }
        Spacer(modifier = Modifier.width(AppSpacing.smallGap))
        PlanRowChevron()
    }
}

@Composable
private fun PlanNextPaymentContent(state: RecurringUiState) {
    val next = planNextFixedPayment(state.items)
    val activeCount = state.items.count { it.status == "active" }
    when {
        next != null -> {
            Row(verticalAlignment = Alignment.CenterVertically) {
                PlanStatusValue(next.merchant, Modifier.weight(1f))
                AppAmountText(
                    text = recurringRecordedAmountText(next.baselineAmountCents, next.homeCurrencyCode),
                    color = MaterialTheme.colorScheme.onSurface,
                    role = AppAmountRole.Compact,
                )
            }
            Text(
                text = recurringNextDateText(recurringItemMeta(next, state.ledgerToday)),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        activeCount > 0 -> PlanStatusValue(stringResource(R.string.plan_status_next_payment_undated, activeCount))
        // 没有生效项时沿用入口行的读取中 / 读取失败 / 空态说明。
        else -> PlanStatusValue(planRecurringSummary(state))
    }
}

@Composable
private fun PlanGoalsContent(state: SpendingGoalsUiState) {
    val goals = planGoalHighlights(state.goals)
    when {
        goals.isNotEmpty() -> {
            if (state.loadError != null) {
                Text(text = state.loadError.asString(), color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall)
            }
            goals.take(PLAN_STATUS_GOAL_LIMIT).forEach { PlanGoalMeter(it) }
            if (goals.size > PLAN_STATUS_GOAL_LIMIT) {
                Text(
                    text = stringResource(R.string.plan_status_goals_more, goals.size - PLAN_STATUS_GOAL_LIMIT),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (state.fromCache) GoalReadSource(state.fetchedAt, fromCache = true)
        }
        state.loadError != null -> PlanStatusValue(state.loadError.asString())
        state.isLoading -> PlanStatusValue(stringResource(R.string.spending_goals_loading_title))
        else -> PlanStatusValue(stringResource(R.string.spending_goals_empty_title))
    }
}

@Composable
private fun PlanGoalMeter(goal: Goal) {
    val attention = goal.progressState == GoalProgressState.OverLimit || goal.progressState == GoalProgressState.NearLimit
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = goal.name,
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = goal.progressPercent?.let { percent ->
                    if (attention) stringResource(R.string.plan_status_goal_used_state, percent, goal.statusText())
                    else stringResource(R.string.plan_status_goal_used, percent)
                } ?: stringResource(R.string.spending_goal_amount_unavailable),
                color = if (attention) goal.stateTone().fg else MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge.tabularNum(),
            )
        }
        if (goal.progress != null) SpendingGoalProgress(goal)
    }
}

@Composable
private fun PlanStatusValue(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        modifier = modifier,
        color = MaterialTheme.colorScheme.onSurface,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
    )
}
