package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Archive
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Goal
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.budget.MonthSwitcher
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel
import com.ticketbox.viewmodel.SpendingGoalEditField

@Composable
internal fun SpendingGoalViewContent(
    goal: Goal,
    canModify: Boolean,
    onArchive: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        SpendingGoalSummaryCard(goal)
        SpendingGoalFactsCard(goal)
        if (canModify && !goal.isArchived) {
            SpendingGoalArchiveCard(onArchive)
        }
    }
}

@Composable
private fun SpendingGoalSummaryCard(goal: Goal) {
    val currency = LocalCurrencyDisplay.current
    AppContentCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = stringResource(R.string.spending_goal_progress_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            StatusPill(text = goal.statusText(), tone = goal.stateTone())
        }
        Text(
            text = stringResource(
                R.string.spending_goal_progress_percent,
                goal.progressPercent.coerceAtLeast(0),
            ),
            color = goal.stateTone().fg,
            style = MaterialTheme.typography.headlineMedium.tabularNum(),
            fontWeight = FontWeight.SemiBold,
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
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ) {
            SpendingGoalMetric(
                label = stringResource(R.string.spending_goal_spent_label),
                value = formatDisplayAmount(goal.spentAmountCents, currency),
                modifier = Modifier.weight(1f),
            )
            SpendingGoalMetric(
                label = if (goal.isOverLimit) {
                    stringResource(R.string.spending_goal_over_label)
                } else {
                    stringResource(R.string.spending_goal_remaining_label)
                },
                value = formatDisplayAmount(kotlin.math.abs(goal.remainingAmountCents), currency),
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun SpendingGoalMetric(
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
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun SpendingGoalFactsCard(goal: Goal) {
    val currency = LocalCurrencyDisplay.current
    AppContentCard {
        Text(
            text = stringResource(R.string.spending_goal_details_section),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        SpendingGoalFactRow(
            label = stringResource(R.string.spending_goal_month_label),
            value = displayMonthLabel(goal.month),
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        SpendingGoalFactRow(
            label = stringResource(R.string.spending_goal_scope_label),
            value = goal.category ?: stringResource(R.string.spending_goal_scope_all),
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        SpendingGoalFactRow(
            label = stringResource(R.string.spending_goal_limit_label),
            value = formatDisplayAmount(goal.targetAmountCents, currency),
        )
    }
}

@Composable
private fun SpendingGoalFactRow(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
internal fun SpendingGoalEditContent(
    state: SpendingGoalDetailUiState,
    viewModel: SpendingGoalDetailViewModel,
) {
    // R14-2：同 CreateSpendingGoalScreen —— 标签随 VM 已解析 capability，未确认落兜底展示。
    val currency = state.ledgerCurrency ?: LocalCurrencyDisplay.current.homeCurrency
    AppContentCard {
        Text(
            text = stringResource(R.string.spending_goal_edit_section),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        MonthSwitcher(
            month = displayMonthLabel(state.month),
            onPreviousMonth = viewModel::previousMonth,
            onNextMonth = viewModel::nextMonth,
        )
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.spending_goal_create_name_label),
                value = state.name,
                placeholder = stringResource(R.string.spending_goal_create_name_placeholder),
                enabled = !state.isSaving,
            ),
            actions = AppTextInputActions(
                onValueChange = { viewModel.updateField(SpendingGoalEditField.Name, it) },
            ),
            modifier = Modifier.fillMaxWidth(),
        )
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.spending_goal_create_amount_label),
                currency = currency,
                value = state.targetAmountInput,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = !state.isSaving,
                isError = state.formError != null && state.targetAmountInput.isBlank(),
            ),
            actions = AppAmountInputActions(
                onValueChange = { viewModel.updateField(SpendingGoalEditField.Amount, it) },
            ),
            modifier = Modifier.fillMaxWidth(),
        )
        SpendingGoalCategoryInput(state = state, viewModel = viewModel)
    }
}

@Composable
private fun SpendingGoalCategoryInput(
    state: SpendingGoalDetailUiState,
    viewModel: SpendingGoalDetailViewModel,
) {
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.spending_goal_create_category_label),
            value = state.category,
            placeholder = stringResource(R.string.spending_goal_create_category_placeholder),
            enabled = !state.isSaving,
        ),
        actions = AppTextInputActions(
            onValueChange = { viewModel.updateField(SpendingGoalEditField.Category, it) },
        ),
        modifier = Modifier.fillMaxWidth(),
    )
    Text(
        text = stringResource(R.string.spending_goal_create_category_hint),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun SpendingGoalArchiveCard(onArchive: () -> Unit) {
    AppContentCard {
        Text(
            text = stringResource(R.string.spending_goal_archive_section),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(R.string.spending_goal_archive_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppOutlinedButton(
            onClick = onArchive,
            modifier = Modifier.fillMaxWidth(),
            options = AppOutlinedButtonOptions(danger = true),
        ) {
            androidx.compose.material3.Icon(Icons.Filled.Archive, contentDescription = null)
            Text(stringResource(R.string.spending_goal_archive_action))
        }
    }
}
