package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
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
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.repository.PendingManualRateSubmission
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.*
import com.ticketbox.viewmodel.BudgetAdviceUiState

internal data class BudgetAdviceActions(val onGenerate: () -> Unit, val onRefreshInputs: () -> Unit,
    val onShiftMonth: (Long) -> Unit, val onOpenRate: (MissingExchangeRateDto) -> Unit,
    val onEditRate: (ExchangeRateDto) -> Unit, val onRateValue: (String) -> Unit,
    val onSaveRate: () -> Unit, val onCloseRate: () -> Unit,
    val onReviewRate: (PendingManualRateSubmission) -> Unit,
    val onRecoverRate: (PendingManualRateSubmission, Boolean) -> Unit)

@Composable
internal fun BudgetAdviceInputsContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        TextButton(onClick = { actions.onShiftMonth(-1) }, enabled = !state.rateBusy) { Text("‹") }
        Text(displayMonthLabel(state.month), style = MaterialTheme.typography.titleMedium)
        TextButton(onClick = { actions.onShiftMonth(1) }, enabled = !state.rateBusy) { Text("›") }
    }
    AppContentCard {
        Text(stringResource(R.string.advice_inputs_title), style = MaterialTheme.typography.titleMedium)
        state.inputs?.let { inputs ->
            val currency = CurrencyDisplay.forRecord(inputs.homeCurrencyCode)
            val amounts = listOf(R.string.advice_inputs_income to inputs.breakdown.monthlyIncomeCents,
                R.string.advice_inputs_fixed to inputs.breakdown.fixedExpensesCents,
                R.string.advice_inputs_spent to inputs.breakdown.spentAmountCents,
                R.string.advice_inputs_available to inputs.breakdown.discretionaryCents)
            amounts.forEach { (label, amount) -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(stringResource(label))
                Text(amount?.let { formatDisplayAmount(it, currency) } ?: stringResource(R.string.advice_inputs_unknown))
            } }
            com.ticketbox.ui.components.CurrencyReferenceDates(inputs.referenceRates.map { it.toDomain() })
            if (inputs.missingRates.isNotEmpty()) Text(stringResource(R.string.advice_missing_rates))
            inputs.missingRates.forEach { gap ->
                if (!gap.canEnterManualRate()) Text(stringResource(R.string.advice_missing_fact))
                else {
                    Text(stringResource(R.string.advice_rate_pair_date, gap.sourceCurrencyCode.orEmpty(), gap.homeCurrencyCode, gap.rateDate.orEmpty()))
                    TextButton(onClick = { actions.onOpenRate(gap) }, enabled = state.canRequest && !state.rateBusy) {
                        Text(stringResource(R.string.advice_rate_add))
                    }
                }
            }
        }
        state.inputsError?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        TextButton(onClick = actions.onRefreshInputs, enabled = !state.inputsLoading) { Text(stringResource(R.string.advice_inputs_refresh)) }
    }
    ManualRateContent(state, actions)
}

@Composable
internal fun ManualRateContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    ManualRateSubmissions(state, actions)
    state.rateMessage?.let { Text(it.asString()) }
    state.rateEditor?.let { ManualRateEditorCard(state, actions) }
    CurrentExchangeRates(state, actions)
}

@Composable
private fun CurrentExchangeRates(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    AppContentCard {
        Text(stringResource(R.string.advice_rates_title), style = MaterialTheme.typography.titleMedium)
        if (state.rates.isEmpty()) Text(stringResource(R.string.advice_rates_empty))
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
