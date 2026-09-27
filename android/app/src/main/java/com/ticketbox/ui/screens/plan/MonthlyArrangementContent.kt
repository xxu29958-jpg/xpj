package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.data.repository.PendingMonthlyArrangement
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.*
import com.ticketbox.viewmodel.BudgetAdviceUiState

@Composable
internal fun MonthlyArrangementContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    var stopId by remember(state.binding) { mutableStateOf<Long?>(null) }
    val pending = state.arrangementPending.filter { it.intent?.month == state.month || it.row.targetId == "monthly_arrangement:${state.month}" }
    MonthlyArrangementEditor(state, actions, pending)
    pending.forEach { submission ->
        MonthlyArrangementSubmission(state, submission, actions) { stopId = submission.row.id }
    }
    if (state.arrangementHistoryLoaded) MonthlyArrangementHistory(state, actions)
    pending.firstOrNull { it.row.id == stopId && it.canDrop }?.let { submission ->
        AlertDialog(onDismissRequest = { stopId = null }, title = { Text(stringResource(R.string.arrangement_stop)) },
            text = { Text(stringResource(R.string.arrangement_stop_body)) },
            confirmButton = { TextButton(onClick = { stopId = null; actions.onRecoverArrangement(submission, true) }) { Text(stringResource(R.string.arrangement_stop)) } },
            dismissButton = { TextButton(onClick = { stopId = null }) { Text(stringResource(R.string.common_cancel)) } })
    }
}

@Composable
private fun MonthlyArrangementEditor(state: BudgetAdviceUiState, actions: BudgetAdviceActions, pending: List<PendingMonthlyArrangement>) {
    val busy = state.arrangementBusy || state.arrangementLoading
    AppContentCard {
        Text(stringResource(R.string.arrangement_title), style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.arrangement_explanation))
        MonthlyArrangementSaved(state)
        state.arrangementDraft?.let {
            Text(stringResource(R.string.arrangement_currency, it.homeCurrencyCode))
            AppTextInput(state = AppTextInputState(label = stringResource(R.string.arrangement_savings), value = it.savings,
                enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)),
                actions = AppTextInputActions(onValueChange = { value -> actions.onArrangementValue(true, value) }),
                modifier = Modifier.fillMaxWidth().testTag("arrangement_savings"))
            AppTextInput(state = AppTextInputState(label = stringResource(R.string.arrangement_buffer), value = it.buffer,
                enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)),
                actions = AppTextInputActions(onValueChange = { value -> actions.onArrangementValue(false, value) }),
                modifier = Modifier.fillMaxWidth().testTag("arrangement_buffer"))
            TextButton(onClick = actions.onTrialArrangement, enabled = !busy,
                modifier = Modifier.testTag("arrangement_trial")) { Text(stringResource(R.string.arrangement_trial)) }
            TextButton(onClick = actions.onSaveArrangement, enabled = !busy && state.canRequest && state.arrangementRead != null && pending.none { p -> !p.isConfirmed },
                modifier = Modifier.testTag("arrangement_save")) { Text(stringResource(R.string.arrangement_save)) }
        }
        TextButton(onClick = actions.onRefreshArrangement, enabled = !busy) { Text(stringResource(R.string.arrangement_refresh)) }
        TextButton(onClick = { actions.onHistory(false) }, enabled = !busy) { Text(stringResource(R.string.arrangement_history)) }
        state.arrangementMessage?.let { Text(it.asString()) }
    }
}

@Composable
private fun MonthlyArrangementSaved(state: BudgetAdviceUiState) {
    val read = state.arrangementRead ?: return
    if (read.fromCache) Text(stringResource(R.string.arrangement_cached))
    val record = read.response.arrangement
    if (record == null) Text(stringResource(R.string.arrangement_not_saved))
    else Text(stringResource(R.string.arrangement_record, record.rowVersion,
        formatDisplayAmount(record.savingsTargetCents, CurrencyDisplay.forRecord(record.homeCurrencyCode)),
        formatDisplayAmount(record.reservedBufferCents, CurrencyDisplay.forRecord(record.homeCurrencyCode))))
}

@Composable
private fun MonthlyArrangementSubmission(state: BudgetAdviceUiState, submission: PendingMonthlyArrangement,
    actions: BudgetAdviceActions, onStop: () -> Unit) {
    val busy = state.arrangementBusy || state.arrangementLoading
    AppContentCard {
        MonthlyArrangementIntentSummary(submission)
        Text(stringResource(if (submission.isConfirmed) R.string.arrangement_confirmed else R.string.arrangement_pending))
        submission.row.lastError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (submission.canRetry) TextButton(onClick = { actions.onRecoverArrangement(submission, false) }, enabled = !busy && state.canRequest) {
            Text(stringResource(R.string.arrangement_retry))
        }
        if (submission.canDrop) {
            TextButton(onClick = { actions.onReviewArrangement(submission) }, enabled = !busy && state.canRequest) { Text(stringResource(R.string.arrangement_review)) }
            TextButton(onClick = onStop, enabled = !busy) { Text(stringResource(R.string.arrangement_stop)) }
        }
    }
}

@Composable
internal fun MonthlyArrangementIntentSummary(submission: PendingMonthlyArrangement) {
    val intent = submission.intent
    if (intent == null) {
        Text(stringResource(R.string.arrangement_original_unsupported))
        return
    }
    Text(stringResource(R.string.arrangement_original_currency, intent.request.homeCurrencyCode))
    Text(stringResource(R.string.arrangement_original, intent.month, submission.row.expectedRowVersion,
        formatDisplayAmount(intent.request.savingsTargetCents, CurrencyDisplay.forRecord(intent.request.homeCurrencyCode)),
        formatDisplayAmount(intent.request.reservedBufferCents, CurrencyDisplay.forRecord(intent.request.homeCurrencyCode))))
}

@Composable
private fun MonthlyArrangementHistory(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    AppContentCard {
        Text(stringResource(R.string.arrangement_history), style = MaterialTheme.typography.titleMedium)
        if (state.arrangementHistoryCached) Text(stringResource(R.string.arrangement_cached))
        if (state.arrangementHistory.isEmpty()) Text(stringResource(R.string.arrangement_history_empty))
        state.arrangementHistory.forEach { item ->
            Text(stringResource(R.string.arrangement_history_item, item.rowVersion, item.recordedAt,
                formatDisplayAmount(item.savingsTargetCents, CurrencyDisplay.forRecord(item.homeCurrencyCode)),
                formatDisplayAmount(item.reservedBufferCents, CurrencyDisplay.forRecord(item.homeCurrencyCode))))
        }
        if (state.arrangementHistoryNext != null) TextButton(onClick = { actions.onHistory(true) },
            enabled = !state.arrangementBusy && !state.arrangementLoading) { Text(stringResource(R.string.arrangement_more)) }
    }
}
