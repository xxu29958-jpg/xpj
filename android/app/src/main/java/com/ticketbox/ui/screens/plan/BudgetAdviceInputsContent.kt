package com.ticketbox.ui.screens.plan

import com.ticketbox.presentation.formatDisplayAmount
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.ExchangeRate
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.data.repository.PendingManualRateSubmission
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.*
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.screens.budget.MonthSwitcher
import com.ticketbox.viewmodel.BudgetAdviceUiState

internal data class BudgetAdviceActions(val onGenerate: () -> Unit, val onRefreshInputs: () -> Unit,
    val onShiftMonth: (Long) -> Unit, val onOpenRate: (CurrencyProjectionGap) -> Unit,
    val onEditRate: (ExchangeRate) -> Unit, val onRateValue: (String) -> Unit,
    val onSaveRate: () -> Unit, val onCloseRate: () -> Unit,
    val onReviewRate: (PendingManualRateSubmission) -> Unit,
    val onRecoverRate: (PendingManualRateSubmission, Boolean) -> Unit,
    val onArrangementValue: (Boolean, String) -> Unit,
    val onTrialArrangement: () -> Unit, val onSaveArrangement: () -> Unit,
    val onRefreshArrangement: () -> Unit, val onHistory: (Boolean) -> Unit,
    val onReviewArrangement: (com.ticketbox.data.repository.PendingMonthlyArrangement) -> Unit,
    val onRecoverArrangement: (com.ticketbox.data.repository.PendingMonthlyArrangement, Boolean) -> Unit,
    val onFetchRates: () -> Unit, val onManualRate: () -> Unit)

@Composable
internal fun BudgetAdviceInputsContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions, onOpenBudget: (() -> Unit)? = null) {
    MonthSwitcher(displayMonthLabel(state.month), onPreviousMonth = { actions.onShiftMonth(-1) },
        onNextMonth = { actions.onShiftMonth(1) }, enabled = !state.rateBusy)
    BudgetAdviceIncome(state)
    state.inputs?.let { MonthlyPlanBudget(it, onOpenBudget) }
    MonthlyArrangementContent(state, actions)
    state.inputs?.let { inputs ->
        Text(stringResource(if (inputs.isTrial) R.string.arrangement_trial_basis else R.string.arrangement_saved_basis))
        inputs.breakdown.shortfallCents?.takeIf { it > 0 }?.let {
            Text(stringResource(R.string.arrangement_shortfall,
                formatDisplayAmount(it, CurrencyDisplay.forRecord(inputs.homeCurrencyCode))), color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun BudgetAdviceIncome(state: BudgetAdviceUiState) {
    val inputs = state.inputs ?: return
    AppPaperCard(containerColor = LocalThemeVisuals.current.brandPrimaryBg) {
        Column(Modifier.padding(AppSpacing.cardPaddingSmall), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.advice_inputs_income), style = MaterialTheme.typography.bodyMedium)
            AppAmountText(inputs.breakdown.monthlyIncomeCents?.let {
                formatDisplayAmount(it, CurrencyDisplay.forRecord(inputs.homeCurrencyCode))
            } ?: stringResource(R.string.advice_inputs_unknown), role = AppAmountRole.Hero)
            Text(stringResource(R.string.arrangement_income_currency, inputs.homeCurrencyCode), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
internal fun BudgetAdviceReferenceContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    var expanded by remember(state.binding, state.month) { mutableStateOf(false) }
    val needsAttention = state.inputsError != null || state.inputs?.readyForAdvice == false ||
        state.rateEditor != null || state.rateSubmissions.isNotEmpty()
    if (!needsAttention) {
        TextButton(onClick = { expanded = !expanded }) {
            Text(stringResource(if (expanded) R.string.arrangement_basis_hide else R.string.arrangement_basis_show))
        }
    }
    if (!expanded && !needsAttention) return
    AppContentCard {
        Text(stringResource(R.string.advice_inputs_title), style = MaterialTheme.typography.titleMedium)
        state.inputs?.let { inputs ->
            MonthlyPlanExplanation(inputs)
            com.ticketbox.ui.components.AccountingDateNotice(inputs.undatedExpenseCount)
            val currency = CurrencyDisplay.forRecord(inputs.homeCurrencyCode)
            val amounts = listOf(R.string.advice_inputs_income to inputs.breakdown.monthlyIncomeCents,
                R.string.advice_inputs_fixed to inputs.breakdown.fixedExpensesCents,
                R.string.advice_inputs_spent to inputs.breakdown.spentAmountCents,
                R.string.arrangement_savings to inputs.breakdown.savingsTargetCents,
                R.string.arrangement_buffer to inputs.breakdown.reservedBufferCents,
                R.string.advice_inputs_available to inputs.breakdown.discretionaryCents)
            amounts.forEach { (label, amount) ->
                AppAdaptiveContentActionRow(style = AppAdaptiveContentActionStyle(compactAction = true),
                    content = { Text(stringResource(label)) }, action = { modifier ->
                        AppEndAlignedAmountText(amount?.let { formatDisplayAmount(it, currency) }
                            ?: stringResource(R.string.advice_inputs_unknown), modifier = modifier, role = AppAmountRole.Compact)
                    })
            }
            com.ticketbox.ui.components.CurrencyReferenceDates(inputs.referenceRates)
            MissingExchangeRates(inputs.missingRates, !state.rateBusy, actions.onOpenRate)
        }
        state.inputsError?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        TextButton(onClick = actions.onRefreshInputs, enabled = !state.inputsLoading) { Text(stringResource(R.string.advice_inputs_refresh)) }
    }
    ManualRateContent(state, actions)
}

@Composable
private fun MissingExchangeRates(rates: List<CurrencyProjectionGap>, enabled: Boolean,
    onOpenRate: (CurrencyProjectionGap) -> Unit) {
    if (rates.isNotEmpty()) Text(stringResource(R.string.advice_missing_rates))
    rates.forEach { gap ->
        if (!gap.canEnterManualRate()) Text(stringResource(R.string.advice_missing_fact))
        else {
            Text(stringResource(R.string.advice_rate_pair_date, gap.sourceCurrencyCode.orEmpty(), gap.homeCurrencyCode, gap.rateDate.orEmpty()))
            TextButton(onClick = { onOpenRate(gap) }, enabled = enabled) {
                Text(stringResource(R.string.advice_rate_add))
            }
        }
    }
}

@Composable
internal fun ManualRateContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    AutomaticRateContent(state, actions)
    ManualRateSubmissions(state, actions)
    state.rateMessage?.let { Text(it.asString()) }
    state.rateEditor?.let { ManualRateEditorCard(state, actions) }
    CurrentExchangeRates(state, actions)
}

@Composable
private fun CurrentExchangeRates(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    if (state.rates.isEmpty()) return
    AppContentCard {
        Text(stringResource(R.string.advice_rates_title), style = MaterialTheme.typography.titleMedium)
        state.rates.forEach { rate ->
            Text(stringResource(R.string.advice_rate_pair_date, rate.currencyCode, rate.homeCurrencyCode, rate.rateDate))
            Text(stringResource(R.string.advice_rate_current, rate.rateToHome, rate.rowVersion))
            TextButton(onClick = { actions.onEditRate(rate) }, enabled = state.canRequest && !state.rateBusy) {
                Text(stringResource(R.string.advice_rate_edit))
            }
        }
    }
}

@Composable
private fun ManualRateEditorCard(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    val editor = state.rateEditor ?: return
    AppContentCard {
        Text(stringResource(R.string.advice_rate_pair_date, editor.currencyCode, editor.homeCurrencyCode, editor.rateDate))
        Text(editor.current?.let { stringResource(R.string.advice_rate_current, it.rateToHome, it.rowVersion) }
            ?: stringResource(R.string.advice_rate_new))
        if (editor.reviewSubmissionId != null) Text(stringResource(R.string.advice_rate_review))
        if (!editor.manualEditing) {
            TextButton(onClick = actions.onManualRate, enabled = !state.rateBusy && state.canRequest) {
                Text(stringResource(R.string.advice_reference_manual))
            }
            TextButton(onClick = actions.onCloseRate, enabled = !state.rateBusy) { Text(stringResource(R.string.advice_reference_choose_again)) }
            return@AppContentCard
        }
        AppTextInput(state = AppTextInputState(label = stringResource(R.string.advice_rate_value, editor.currencyCode, editor.homeCurrencyCode),
            value = editor.value, enabled = !state.rateBusy && state.canRequest,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)),
            actions = AppTextInputActions(onValueChange = actions.onRateValue),
            modifier = Modifier.fillMaxWidth().testTag("advice_rate_value"))
        Row {
            TextButton(onClick = actions.onCloseRate, enabled = !state.rateBusy) { Text(stringResource(R.string.common_cancel)) }
            TextButton(onClick = actions.onSaveRate, enabled = !state.rateBusy && state.canRequest,
                modifier = Modifier.testTag("advice_rate_save")) { Text(stringResource(R.string.advice_rate_submit)) }
        }
    }
}

@Composable
internal fun ManualRateSubmissionSummary(pending: PendingManualRateSubmission) {
    val intent = pending.intent
    if (intent == null) Text(stringResource(R.string.advice_rate_submission_review))
    else {
        val request = intent.request
        Text(stringResource(R.string.advice_rate_original_month, intent.month))
        Text(stringResource(R.string.advice_rate_pair_date, request.currencyCode, request.homeCurrencyCode, request.rateDate))
        Text(stringResource(R.string.advice_rate_original_value, request.currencyCode, request.rateToHome, request.homeCurrencyCode))
    }
    Text(stringResource(R.string.advice_rate_original_details, pending.row.idempotencyKey.orEmpty(), pending.row.expectedRowVersion),
        style = MaterialTheme.typography.bodySmall)
    Text(stringResource(when {
        pending.isConfirmed -> R.string.advice_rate_submission_done
        pending.canDrop -> R.string.advice_rate_submission_review
        else -> R.string.advice_rate_submission_pending
    }))
}

@Composable
private fun ManualRateSubmissions(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    var stopId by remember(state.binding) { mutableStateOf<Long?>(null) }
    val selected = state.selectedRateSubmissionId
    if (selected != null && state.rateSubmissions.none { it.row.id == selected }) Text(stringResource(R.string.advice_rate_submission_missing))
    state.rateSubmissions.sortedByDescending { it.row.id == selected }.forEach { pending ->
        AppContentCard {
            ManualRateSubmissionSummary(pending)
            if (pending.canRetry) TextButton(onClick = { actions.onRecoverRate(pending, false) }, enabled = !state.rateBusy && state.canRequest) {
                Text(stringResource(R.string.advice_rate_retry))
            }
            if (pending.canDrop) {
                TextButton(onClick = { actions.onReviewRate(pending) }, enabled = !state.rateBusy && state.canRequest) {
                    Text(stringResource(R.string.advice_rate_review_current))
                }
                TextButton(onClick = { stopId = pending.row.id }, enabled = !state.rateBusy) { Text(stringResource(R.string.advice_rate_stop)) }
            }
        }
    }
    val stopping = state.rateSubmissions.firstOrNull { it.row.id == stopId && it.canDrop }
    if (stopping != null) AlertDialog(onDismissRequest = { stopId = null },
        title = { Text(stringResource(R.string.advice_rate_stop)) }, text = { Text(stringResource(R.string.advice_rate_stop_body)) },
        confirmButton = { TextButton(onClick = { stopId = null; actions.onRecoverRate(stopping, true) }) { Text(stringResource(R.string.advice_rate_stop)) } },
        dismissButton = { TextButton(onClick = { stopId = null }) { Text(stringResource(R.string.common_cancel)) } })
}
