package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.data.repository.bindingOrNull
import com.ticketbox.data.repository.canonicalServerOriginOrNull
import com.ticketbox.data.repository.expenseRefreshVersion
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Establish the durable snapshot before reads, so historical delivery is not a new edit. */
internal fun ExpenseFactViewModel.observeFactSubmissions(onBindingSnapshot: () -> Unit) {
    viewModelScope.launch {
        combine(repository.observeCorrections(), repository.observeExpenseOutboxStatus()) { corrections, status ->
            corrections to status
        }.collect { (observation, status) ->
            reconcileFactSubmissions(observation, status, onBindingSnapshot)
        }
    }
}

private fun ExpenseFactViewModel.reconcileFactSubmissions(
    observation: ExpenseCorrectionObservation,
    status: OutboxStatus,
    onBindingSnapshot: () -> Unit,
) {
    if (_uiState.value.correctionAccess?.binding != observation.access?.binding) resetFactBinding()
    val corrections = observation.corrections.filter { it.expenseId == expenseId }
    val previousDone = observedCorrectionCompletions
    val newlyDelivered = corrections.filter { previousDone != null && it.delivered && it.row.id !in previousDone }
    val refreshRows = boundExpenseRefreshRows(status, observation.access?.binding)
    val previousRefreshRows = _uiState.value.expenseRefreshRequirements
    val newlyRequired = refreshRows.any { row -> previousRefreshRows.none { it.id == row.id && it.lastError == row.lastError } }
    val acknowledged = refreshWasAcknowledged(corrections, refreshRows)
    val refreshRequired = newlyRequired || shouldRefreshAcknowledgedRoot(acknowledged)
    val needsRefresh = newlyDelivered.isNotEmpty() || refreshRequired
    val requiredVersion = (corrections.filter { it.refreshRequired }.map { it.row } + refreshRows)
        .mapNotNull { expenseRefreshVersion(it.lastError) }.maxOrNull() ?: 0L
    _uiState.update {
        it.copy(
            correctionAccess = observation.access,
            corrections = corrections,
            expenseRefreshRequirements = refreshRows,
            requiredRootRowVersion = maxOf(it.requiredRootRowVersion, requiredVersion),
            readOnly = observation.access?.canModify != true,
            expenseLoading = it.expenseLoading || needsRefresh,
            expenseLoadState = if (needsRefresh) ExpenseDetailDataLoadState.Loading else it.expenseLoadState,
        )
    }
    observedCorrectionCompletions = corrections.filter { it.delivered }.map { it.row.id }.toSet()
    when {
        observation.access == null -> observedCorrectionCompletions = null
        previousDone == null -> onBindingSnapshot()
        else -> refreshNewCorrectionCompletions(newlyDelivered, refreshRequired)
    }
}

/** Old binding emissions cannot acknowledge this binding's already-observed requirement. */
private fun ExpenseFactViewModel.boundExpenseRefreshRows(status: OutboxStatus, binding: LogicalSessionBinding?): List<OutboxRow> {
    if (!status.binding.matchesFactBinding(binding)) return _uiState.value.expenseRefreshRequirements
    return status.refreshRequired.filter { row ->
        row.type != PendingMutationType.CorrectExpense && row.targetId == "expense:$expenseId" &&
            row.bindingOrNull().matchesFactBinding(binding)
    }
}

private fun OutboxBinding?.matchesFactBinding(binding: LogicalSessionBinding?): Boolean =
    this != null && binding != null && ownerStorageKey == binding.ownerKey && ledgerId == binding.ledgerId &&
        canonicalServerOriginOrNull(serverUrl)?.let { it == canonicalServerOriginOrNull(binding.serverUrl) } == true

private fun ExpenseFactViewModel.refreshWasAcknowledged(corrections: List<PendingExpenseCorrection>, rows: List<OutboxRow>): Boolean =
    _uiState.value.corrections.any { previous -> previous.refreshRequired && corrections.none {
        it.row.id == previous.row.id && it.refreshRequired
    } } || _uiState.value.expenseRefreshRequirements.any { previous -> rows.none { it.id == previous.id } }

/** Retire facts, drafts and in-flight reads together when their original session changes. */
private fun ExpenseFactViewModel.resetFactBinding() {
    correctionSplitMemberGeneration++
    correctionBaseline = null
    correctionBinding = null
    correctionOriginalItems = null
    correctionOriginalSplits = null
    observedCorrectionCompletions = null
    factBundleLoadGeneration++
    revisionLoadGeneration++
    expenseLoadGeneration++
    expenseReadInFlightGeneration = null
    itemsLoadGeneration++
    splitsLoadGeneration++
    thumbnailLoadGeneration++
    fullImageLoadGeneration++
    _uiState.value = ExpenseFactUiState(readOnly = true)
}

private fun ExpenseFactViewModel.shouldRefreshAcknowledgedRoot(acknowledged: Boolean): Boolean {
    val state = _uiState.value
    return acknowledged && (state.expense?.rowVersion ?: 0L) < state.requiredRootRowVersion &&
        expenseReadInFlightGeneration == null && !state.initialRootVerificationPending &&
        state.factBundleLoadState != ExpenseDetailDataLoadState.Loading
}
