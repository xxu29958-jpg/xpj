package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

data class ManualRateEditor(val binding: LogicalSessionBinding, val currencyCode: String,
    val homeCurrencyCode: String, val rateDate: String, val current: ExchangeRateDto?,
    val value: String, val reviewSubmissionId: Long? = null)

internal fun BudgetAdviceViewModel.observeAdviceAccess() {
    viewModelScope.launch {
        var observedRole: String? = null
        repository.observeLedgerAccessState().distinctUntilChanged().collect { access ->
            val previousRole = observedRole
            observedRole = access?.role
            if (_state.value.binding == access?.binding) {
                onRoleReprojection(previousRole, access?.role)
                return@collect
            }
            requestGeneration += 1
            inputGeneration += 1
            rateObservation?.cancel()
            _state.update { current -> BudgetAdviceUiState(month = current.month,
                binding = access?.binding, canRequest = access?.canModify == true,
                selectedRateSubmissionId = current.selectedRateSubmissionId.takeUnless { observedInputBinding }) }
            observedInputBinding = true
            access?.let {
                observeRateSubmissions(it.binding)
                refreshInputs()
            }
        }
    }
}

private fun BudgetAdviceViewModel.observeRateSubmissions(binding: LogicalSessionBinding) {
    rateObservation = viewModelScope.launch {
        var seen: Set<Long>? = null
        repository.observeRates(binding).collect { rows ->
            if (_state.value.binding != binding) return@collect
            val confirmed = rows.filter { it.isConfirmed }.map { it.row.id }.toSet()
            val newlyConfirmed = seen?.let { confirmed - it }.orEmpty()
            seen = confirmed
            _state.update { it.copy(rateSubmissions = rows) }
            _state.value.selectedRateSubmissionId?.let { openRateSubmission(it) }
            if (newlyConfirmed.isNotEmpty()) refreshInputs()
        }
    }
}

/** A rate acknowledgement refreshes inputs and canonical rates, never the live provider. */
fun BudgetAdviceViewModel.refreshInputs() {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    val generation = ++inputGeneration
    _state.update { it.copy(inputsLoading = true, inputsError = null) }
    viewModelScope.launch {
        val inputs = repository.adviceInputs(binding, snapshot.month, snapshot.reportingHomeCurrencyCode)
        val rates = repository.exchangeRates(binding)
        if (_state.value.binding != binding || _state.value.month != snapshot.month || generation != inputGeneration) return@launch
        _state.update { current -> current.copy(inputsLoading = false,
            inputs = inputs.getOrNull(), rates = rates.getOrNull() ?: current.rates,
            reportingHomeCurrencyCode = inputs.getOrNull()?.homeCurrencyCode ?: current.reportingHomeCurrencyCode,
            inputsError = inputs.exceptionOrNull()?.toUiText(R.string.advice_inputs_load_failed)
                ?: rates.exceptionOrNull()?.toUiText(R.string.advice_rates_load_failed)) }
        if (inputs.getOrNull()?.readyForAdvice == false) {
            _state.update { it.copy(result = null, loadState = BudgetAdviceLoadState.Idle) }
        } else if (_state.value.loadState == BudgetAdviceLoadState.Idle) restoreCachedAdvice()
    }
}

fun BudgetAdviceViewModel.shiftMonth(delta: Long) {
    if (_state.value.rateBusy || _state.value.loadState == BudgetAdviceLoadState.Loading) return
    val month = runCatching { YearMonth.parse(_state.value.month).plusMonths(delta).toString() }.getOrNull() ?: return
    requestGeneration += 1
    _state.update { it.copy(month = month, inputs = null, result = null, loadState = BudgetAdviceLoadState.Idle,
        error = null, terminalErrorCode = null, selectedRateSubmissionId = null, rateEditor = null) }
    refreshInputs()
}

fun BudgetAdviceViewModel.openRateSubmission(id: Long) {
    _state.update { it.copy(selectedRateSubmissionId = id) }
    val original = _state.value.rateSubmissions.firstOrNull { it.row.id == id } ?: return
    val intent = original.intent?.takeIf { it.supports(original.row) } ?: return
    val month = intent.month
    val home = intent.request.homeCurrencyCode
    if (_state.value.month != month || _state.value.reportingHomeCurrencyCode != home) {
        requestGeneration += 1
        _state.update { it.copy(month = month, reportingHomeCurrencyCode = home, inputs = null, result = null,
            rateEditor = null, loadState = BudgetAdviceLoadState.Idle) }
        refreshInputs()
    }
}
