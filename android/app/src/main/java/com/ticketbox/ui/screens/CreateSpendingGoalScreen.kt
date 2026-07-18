package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.budget.MonthSwitcher
import com.ticketbox.viewmodel.CreateSpendingGoalUiState
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import java.time.YearMonth

@Composable
fun CreateSpendingGoalScreen(
    viewModel: CreateSpendingGoalViewModel,
    initialMonth: String = YearMonth.now().toString(),
    onBack: () -> Unit,
    onCreated: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(initialMonth) { viewModel.reset(initialMonth) }
    LaunchedEffect(state.createdPublicId) {
        if (state.createdPublicId != null) {
            onCreated()
            viewModel.consumeCreated()
        }
    }

    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.spending_goal_create_title),
            subtitle = stringResource(R.string.spending_goal_create_intro),
            backText = stringResource(R.string.spending_goal_create_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        slots = AppSecondaryPageSlots(
            status = { CreateSpendingGoalStatusStack(state = state) },
            bottomBar = {
                CreateSpendingGoalFooter(
                    canSubmit = state.canSubmit,
                    isSubmitting = state.isSubmitting,
                    onSubmit = viewModel::submit,
                )
            },
        ),
    ) { _ ->
        DebtGoalOpenSection(
            title = stringResource(R.string.spending_goal_create_month_section),
            subtitle = stringResource(R.string.spending_goal_create_month_hint),
        ) {
            MonthSwitcher(
                month = displayMonthLabel(state.month),
                onPreviousMonth = viewModel::previousMonth,
                onNextMonth = viewModel::nextMonth,
            )
        }
        DebtGoalOpenSection(
            title = stringResource(R.string.spending_goal_create_form_section),
            subtitle = stringResource(R.string.spending_goal_create_form_hint),
        ) {
            SpendingGoalForm(state = state, viewModel = viewModel)
        }
    }
}

@Composable
private fun CreateSpendingGoalStatusStack(state: CreateSpendingGoalUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppDataAuthorityStrip(
            tone = if (state.isSubmitting) DataAuthorityTone.Refreshing else DataAuthorityTone.Backend,
        )
        if (!state.canModify) {
            AppStatusBanner(
                message = UiText.res(R.string.common_readonly_ledger),
                tone = MessageTone.Info,
                announceUpdates = false,
            )
        }
        state.formError?.let { err -> AppStatusBanner(message = err, tone = MessageTone.Danger) }
    }
}

@Composable
private fun SpendingGoalForm(
    state: CreateSpendingGoalUiState,
    viewModel: CreateSpendingGoalViewModel,
) {
    val currency = LocalCurrencyDisplay.current.homeCurrency
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.spending_goal_create_name_label),
                value = state.name,
                placeholder = stringResource(R.string.spending_goal_create_name_placeholder),
                enabled = !state.isSubmitting && state.canModify,
            ),
            actions = AppTextInputActions(onValueChange = viewModel::updateName),
            modifier = Modifier.fillMaxWidth(),
        )
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.spending_goal_create_amount_label),
                currency = currency,
                value = state.targetAmountInput,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = !state.isSubmitting && state.canModify,
                isError = state.formError != null && state.targetAmountInput.isBlank(),
            ),
            actions = AppAmountInputActions(onValueChange = viewModel::updateTargetAmount),
            modifier = Modifier.fillMaxWidth(),
        )
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.spending_goal_create_category_label),
                value = state.category,
                placeholder = stringResource(R.string.spending_goal_create_category_placeholder),
                enabled = !state.isSubmitting && state.canModify,
            ),
            actions = AppTextInputActions(onValueChange = viewModel::updateCategory),
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            text = stringResource(R.string.spending_goal_create_category_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun CreateSpendingGoalFooter(
    canSubmit: Boolean,
    isSubmitting: Boolean,
    onSubmit: () -> Unit,
) {
    AppFloatingActionBar {
        AppPrimaryButton(
            text = if (isSubmitting) {
                stringResource(R.string.spending_goal_create_submitting)
            } else {
                stringResource(R.string.spending_goal_create_save)
            },
            icon = Icons.Filled.Check,
            modifier = Modifier.fillMaxWidth(),
            enabled = canSubmit,
            onClick = onSubmit,
        )
    }
}
