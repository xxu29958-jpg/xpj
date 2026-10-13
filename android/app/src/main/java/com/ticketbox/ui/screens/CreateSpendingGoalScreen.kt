package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.budget.MonthSwitcher
import com.ticketbox.viewmodel.CreateSpendingGoalUiState
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel

@Composable
fun CreateSpendingGoalScreen(
    viewModel: CreateSpendingGoalViewModel,
    initialMonth: String? = null,
    onBack: () -> Unit,
    onCreated: () -> Unit,
    originalId: Long? = null,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val showDraft = state.pending == null ||
        (state.hasDraft && !state.isViewingOriginal && state.pending?.needsRetainedDraft == true)
    LaunchedEffect(viewModel, initialMonth, originalId) { viewModel.reset(initialMonth, originalId) }
    LaunchedEffect(state.createdPublicId) {
        if (state.createdPublicId != null) {
            onCreated()
            viewModel.consumeCreated()
        }
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.spending_goal_create_title),
            subtitle = stringResource(R.string.spending_goal_create_intro),
            backText = stringResource(R.string.spending_goal_create_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        refresh = AppSecondaryRefreshState(isRefreshing = false, onRefresh = {}),
        slots = AppSecondaryPageSlots(
            status = { CreateSpendingGoalStatusStack(state = state, onRetryCurrency = viewModel::retryCurrency)
                state.pending?.let { GoalCreationSubmissionStatus(it, state.isSubmitting, state.canModify, viewModel::recover) }
                SpendingGoalDraftActions(state, viewModel) { viewModel.discardDraft(); onBack() }
            },
            bottomBar = {
                CreateSpendingGoalFooter(
                    canSubmit = state.canSubmit,
                    isSubmitting = state.isSubmitting,
                    onSubmit = viewModel::submit,
                )
            },
        ),
    ) {
        if (showDraft) item {
            DebtGoalOpenSection(
                title = stringResource(R.string.spending_goal_create_month_section),
                subtitle = stringResource(R.string.spending_goal_create_month_hint),
            ) {
                MonthSwitcher(
                    month = displayMonthLabel(state.month),
                    onPreviousMonth = { viewModel.shiftMonth(-1) },
                    onNextMonth = { viewModel.shiftMonth(1) },
                    enabled = state.editable,
                )
            }
        }
        if (showDraft) item {
            DebtGoalOpenSection(
                title = stringResource(R.string.spending_goal_create_form_section),
                subtitle = stringResource(R.string.spending_goal_create_form_hint),
            ) {
                SpendingGoalForm(state = state, viewModel = viewModel)
            }
        }
    }
}

@Composable
private fun SpendingGoalDraftActions(
    state: CreateSpendingGoalUiState,
    viewModel: CreateSpendingGoalViewModel,
    onDiscard: () -> Unit,
) {
    if (!state.hasDraft || state.isViewingOriginal) return
    var confirmDiscard by rememberSaveable(state.creationKey) { mutableStateOf(false) }
    if (state.acceptanceUncertain) TextButton(enabled = !state.isSubmitting && !state.checkingOriginal, onClick = viewModel::retryOriginal) {
        Text(stringResource(R.string.goal_draft_check_original))
    }
    TextButton(enabled = state.canDiscardDraft, onClick = { confirmDiscard = true }) {
        Text(stringResource(R.string.goal_draft_discard))
    }
    if (confirmDiscard) AlertDialog(
        onDismissRequest = { confirmDiscard = false },
        title = { Text(stringResource(R.string.goal_draft_discard)) },
        text = { Text(stringResource(R.string.goal_draft_discard_explanation)) },
        confirmButton = { TextButton(enabled = state.canDiscardDraft, onClick = { confirmDiscard = false; onDiscard() }) {
            Text(stringResource(R.string.goal_draft_discard_confirm))
        } },
        dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
}

@Composable
private fun CreateSpendingGoalStatusStack(state: CreateSpendingGoalUiState, onRetryCurrency: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (!state.canModify) {
            AppStatusBanner(message = UiText.res(R.string.common_readonly_ledger), tone = MessageTone.Info)
        }
        state.formError?.let { err -> AppStatusBanner(message = err, tone = MessageTone.Danger) }
        if (state.ledgerCurrency == null && state.originalSubmissionId == null) TextButton(onClick = onRetryCurrency) {
            Text(stringResource(R.string.common_retry))
        }
    }
}

@Composable
private fun SpendingGoalForm(
    state: CreateSpendingGoalUiState,
    viewModel: CreateSpendingGoalViewModel,
) {
    val currency = state.ledgerCurrency
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.spending_goal_create_name_label),
                value = state.name,
                placeholder = stringResource(R.string.spending_goal_create_name_placeholder),
                enabled = state.editable,
            ),
            actions = AppTextInputActions(onValueChange = viewModel::updateName),
            modifier = Modifier.fillMaxWidth(),
        )
        if (currency != null) {
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.spending_goal_create_amount_label),
                currency = currency,
                value = state.targetAmountInput,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = state.editable,
                isError = state.formError != null && state.targetAmountInput.isBlank(),
            ),
            actions = AppAmountInputActions(onValueChange = viewModel::updateTargetAmount),
            modifier = Modifier.fillMaxWidth(),
        )
        } else {
            Text(stringResource(R.string.spending_goal_currency_loading))
        }
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.spending_goal_create_category_label),
                value = state.category,
                placeholder = stringResource(R.string.spending_goal_create_category_placeholder),
                enabled = state.editable,
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
            icons = AppButtonIcons(leading = Icons.Filled.Check),
            modifier = Modifier.fillMaxWidth(),
            enabled = canSubmit,
            onClick = onSubmit,
        )
    }
}
