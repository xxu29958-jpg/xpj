package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Archive
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Goal
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
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
        com.ticketbox.ui.components.AccountingDateNotice(goal.undatedExpenseCount)
        SpendingGoalSummaryCard(goal)
        SpendingGoalFactsCard(goal)
        if (canModify && !goal.isArchived) {
            SpendingGoalArchiveEntry(onArchive)
        }
    }
}

@Composable
private fun SpendingGoalFactsCard(goal: Goal) {
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
    }
}

@Composable
private fun SpendingGoalFactRow(
    label: String,
    value: String,
) {
    AppAdaptiveContentActionRow(
        style = AppAdaptiveContentActionStyle(compactAction = true, wideActionWeight = 1f),
        content = { Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        ) },
        action = { Text(
            text = value,
            modifier = it,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
        ) },
    )
}

@Composable
internal fun SpendingGoalEditContent(
    state: SpendingGoalDetailUiState,
    viewModel: SpendingGoalDetailViewModel,
) {
    val currency = state.goalCurrency
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
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
        MonthSwitcher(
            month = displayMonthLabel(state.month),
            onPreviousMonth = { viewModel.shiftMonth(-1) },
            onNextMonth = { viewModel.shiftMonth(1) },
        )
        if (currency != null) {
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
        } else {
            Text(stringResource(R.string.spending_goal_currency_loading))
        }
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
private fun SpendingGoalArchiveEntry(onArchive: () -> Unit) {
    // 归档是低频破坏性动作：文字级入口 + 既有确认弹窗，不再占一张大卡。
    val danger = LocalStateTokens.current.danger.fg
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        TextButton(onClick = onArchive) {
            Icon(
                imageVector = Icons.Filled.Archive,
                contentDescription = null,
                tint = danger,
            )
            Spacer(modifier = Modifier.width(AppSpacing.miniGap))
            Text(
                text = stringResource(R.string.spending_goal_archive_action),
                color = danger,
            )
        }
    }
}
