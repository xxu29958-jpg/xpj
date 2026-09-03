package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.EventRepeat
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Handshake
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.budget.BudgetProgressBar
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.IncomePlanLoadState
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringUiState

private data class PlanRowModel(
    val title: String,
    val subtitle: String,
    val icon: ImageVector,
    val testTag: String,
    val onClick: () -> Unit,
)

@Composable
internal fun PlanBudgetSection(
    state: BudgetUiState,
    actions: PlanBudgetNavigationActions,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        PlanSectionTitle(stringResource(R.string.plan_section_month))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
        val budget = state.budget?.takeIf { it.configured }
        if (budget == null) {
            PlanDestinationRow(
                model = PlanRowModel(
                    title = stringResource(R.string.plan_budget_title),
                    subtitle = planBudgetFallbackSummary(state),
                    icon = Icons.Filled.AccountBalanceWallet,
                    testTag = PlanDestinationTestTags.Budget,
                    onClick = actions.onOpenBudget,
                ),
            )
        } else {
            PlanConfiguredBudget(
                state = state,
                budget = budget,
                onOpenBudget = actions.onOpenBudget,
            )
        }
        PlanDestinationRow(
            model = PlanRowModel(
                title = stringResource(R.string.plan_budget_advice_title),
                subtitle = stringResource(R.string.plan_budget_advice_subtitle),
                icon = Icons.Filled.Tune,
                testTag = PlanDestinationTestTags.BudgetAdvice,
                onClick = actions.onOpenAdvice,
            ),
        )
    }
}

@Composable
private fun PlanConfiguredBudget(
    state: BudgetUiState,
    budget: BudgetMonthly,
    onOpenBudget: () -> Unit,
) {
    val currency = LocalCurrencyDisplay.current
    val danger = LocalStateTokens.current.danger.fg
    val amount = if (budget.isOverBudget) budget.overspentAmountCents else budget.remainingAmountCents
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(PlanDestinationTestTags.Budget)
            .clickable(role = Role.Button, onClick = onOpenBudget)
            .padding(vertical = AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = if (budget.isOverBudget) {
                        stringResource(R.string.plan_budget_over_label)
                    } else {
                        stringResource(R.string.plan_budget_remaining_label)
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    text = formatDisplayAmount(amount, currency),
                    color = if (budget.isOverBudget) danger else MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.displayMedium.tabularNum(),
                )
            }
            PlanRowChevron(modifier = Modifier.align(Alignment.CenterVertically))
        }
        BudgetProgressBar(progress = budget.spentProgress)
        Text(
            text = stringResource(
                R.string.plan_budget_progress_meta,
                formatDisplayAmount(budget.spentAmountCents, currency),
                formatDisplayAmount(budget.availableAmountCents, currency),
                budget.spentPercent,
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall.tabularNum(),
        )
        state.loadError?.let {
            Text(
                text = it.asString(),
                color = danger,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
}

@Composable
internal fun PlanGoalsSection(
    onOpenSpendingGoal: () -> Unit,
    onOpenDebtGoal: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        PlanSectionTitle(stringResource(R.string.plan_section_goals))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
        PlanDestinationRow(
            model = PlanRowModel(
                title = stringResource(R.string.plan_spending_goal_title),
                subtitle = stringResource(R.string.plan_spending_goal_subtitle),
                icon = Icons.Filled.Flag,
                testTag = PlanDestinationTestTags.SpendingGoal,
                onClick = onOpenSpendingGoal,
            ),
        )
        PlanDestinationRow(
            model = PlanRowModel(
                title = stringResource(R.string.plan_debt_goal_title),
                subtitle = stringResource(R.string.plan_debt_goal_subtitle),
                icon = Icons.Filled.Handshake,
                testTag = PlanDestinationTestTags.DebtGoal,
                onClick = onOpenDebtGoal,
            ),
        )
    }
}

@Composable
internal fun PlanFixedArrangementsSection(
    recurring: RecurringUiState,
    income: IncomePlanUiState,
    onOpenRecurring: () -> Unit,
    onOpenIncomePlans: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        PlanSectionTitle(stringResource(R.string.plan_section_ongoing))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
        PlanDestinationRow(
            model = PlanRowModel(
                title = stringResource(R.string.plan_recurring_title),
                subtitle = planRecurringSummary(recurring),
                icon = Icons.Filled.EventRepeat,
                testTag = PlanDestinationTestTags.Recurring,
                onClick = onOpenRecurring,
            ),
        )
        PlanDestinationRow(
            model = PlanRowModel(
                title = stringResource(R.string.plan_income_title),
                subtitle = planIncomeSummary(income),
                icon = Icons.Filled.Payments,
                testTag = PlanDestinationTestTags.IncomePlans,
                onClick = onOpenIncomePlans,
            ),
        )
    }
}

@Composable
private fun PlanSectionTitle(title: String) {
    Text(
        text = title,
        modifier = Modifier.padding(bottom = AppSpacing.smallGap),
        color = MaterialTheme.colorScheme.onSurface,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
    )
}

@Composable
private fun PlanDestinationRow(
    model: PlanRowModel,
    showDivider: Boolean = true,
) {
    AppListRow(
        modifier = Modifier.testTag(model.testTag),
        onClick = model.onClick,
        showDivider = showDivider,
    ) {
        Icon(
            imageVector = model.icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
        Spacer(modifier = Modifier.width(AppSpacing.compactGap))
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = model.title,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = model.subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(modifier = Modifier.width(AppSpacing.smallGap))
        PlanRowChevron(
            modifier = Modifier.align(Alignment.CenterVertically),
        )
    }
}

/** W2-C：入口行 trailing 统一为 chevron（旧 设置/调整/查看/管理/打开 动词族退役）。 */
@Composable
private fun PlanRowChevron(
    modifier: Modifier = Modifier,
) {
    Icon(
        imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
        contentDescription = null,
        tint = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier.size(AppSpacing.cardPadding),
    )
}

@Composable
private fun planBudgetFallbackSummary(state: BudgetUiState): String = when {
    state.loading && state.budget == null -> stringResource(R.string.plan_budget_loading)
    state.loadError != null -> state.loadError.asString()
    else -> stringResource(R.string.plan_budget_empty)
}

@Composable
private fun planRecurringSummary(state: RecurringUiState): String {
    val active = state.items.filter { it.status.equals("active", ignoreCase = true) }
    val activeAmount = active.sumOf { it.baselineAmountCents }
    val currency = LocalCurrencyDisplay.current
    return when {
        state.itemsLoadState == RecurringListLoadState.Failed && active.isEmpty() ->
            state.message?.asString() ?: stringResource(R.string.plan_recurring_error)
        (state.itemsLoadState == RecurringListLoadState.Unknown ||
            state.itemsLoadState == RecurringListLoadState.Loading) &&
            active.isEmpty() -> stringResource(R.string.plan_recurring_loading)
        active.isEmpty() && state.candidates.isNotEmpty() ->
            stringResource(R.string.plan_recurring_empty_with_candidates, state.candidates.size)
        active.isEmpty() -> stringResource(R.string.plan_recurring_empty)
        state.candidatesLoadState == RecurringListLoadState.Failed ->
            stringResource(
                R.string.plan_recurring_summary_partial,
                active.size,
                formatDisplayAmount(activeAmount, currency),
            )
        state.candidates.isNotEmpty() ->
            stringResource(
                R.string.plan_recurring_summary_with_candidates,
                active.size,
                formatDisplayAmount(activeAmount, currency),
                state.candidates.size,
            )
        else -> stringResource(
            R.string.plan_recurring_summary,
            active.size,
            formatDisplayAmount(activeAmount, currency),
        )
    }
}

@Composable
private fun planIncomeSummary(state: IncomePlanUiState): String = when {
    state.loadState == IncomePlanLoadState.Failed && state.activePlans.isEmpty() ->
        state.error?.asString() ?: stringResource(R.string.plan_income_error)
    (state.loadState == IncomePlanLoadState.Unknown || state.loadState == IncomePlanLoadState.Loading) &&
        state.activePlans.isEmpty() -> stringResource(R.string.plan_income_loading)
    state.activePlans.isEmpty() -> stringResource(R.string.plan_income_empty)
    else -> stringResource(
        R.string.plan_income_summary,
        state.currentMonthSummary.effectivePlanCount,
        formatDisplayAmount(
            state.currentMonthSummary.expectedAmountCents,
            LocalCurrencyDisplay.current,
        ),
        state.currentMonthSummary.historicalRecordCount,
    )
}
