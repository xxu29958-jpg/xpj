package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.repository.PendingManualRateSubmission
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canonicalManualExchangeRateOrNull
import com.ticketbox.domain.model.sanitizeManualExchangeRateInput
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

fun BudgetAdviceViewModel.openRate(gap: MissingExchangeRateDto, original: PendingManualRateSubmission? = null) {
    val binding = _state.value.binding ?: return
    val month = _state.value.month
    if (!_state.value.canRequest || !gap.canEnterManualRate() || _state.value.rateBusy) return
    _state.update { it.copy(rateBusy = true, rateMessage = null) }
    viewModelScope.launch {
        val response = repository.exchangeRates(binding, gap.sourceCurrencyCode, gap.homeCurrencyCode, gap.rateDate)
        if (_state.value.binding != binding) return@launch
        if (_state.value.month != month) {
            _state.update { it.copy(rateBusy = false) }
            return@launch
        }
        response.fold(onSuccess = { rates ->
            val current = rates.singleOrNull()
            _state.update { it.copy(rateBusy = false, rateEditor = ManualRateEditor(binding,
                requireNotNull(gap.sourceCurrencyCode), gap.homeCurrencyCode, requireNotNull(gap.rateDate), current,
                original?.intent?.request?.rateToHome ?: current?.rateToHome.orEmpty(), original?.row?.id)) }
        }, onFailure = { error -> _state.update { it.copy(rateBusy = false,
            rateMessage = error.toUiText(R.string.advice_rates_load_failed)) } })
    }
}

fun BudgetAdviceViewModel.editRate(rate: ExchangeRateDto) =
    openRate(MissingExchangeRateDto(rate.currencyCode, rate.homeCurrencyCode, rate.rateDate))

fun BudgetAdviceViewModel.updateRateInput(value: String) {
    if (_state.value.rateBusy) return
    _state.update { it.copy(rateEditor = it.rateEditor?.copy(value = sanitizeManualExchangeRateInput(value)), rateMessage = null) }
}

fun BudgetAdviceViewModel.closeRateEditor() {
    if (!_state.value.rateBusy) _state.update { it.copy(rateEditor = null, rateMessage = null) }
}

fun BudgetAdviceViewModel.saveRate() {
    val snapshot = _state.value
    val editor = snapshot.rateEditor ?: return
    if (snapshot.rateBusy || !snapshot.canRequest || snapshot.binding != editor.binding) return
    val value = canonicalManualExchangeRateOrNull(editor.value)
    if (value == null) {
        _state.update { it.copy(rateMessage = UiText.res(R.string.expense_edit_manual_rate_invalid)) }
        return
    }
    _state.update { it.copy(rateBusy = true, rateMessage = null) }
    viewModelScope.launch {
        val request = ExchangeRateRequestDto(editor.currencyCode, editor.homeCurrencyCode, editor.rateDate,
            value, "manual", editor.current?.rowVersion ?: 0)
        val result = repository.enqueueRate(editor.binding, snapshot.month, request, editor.current?.publicId)
        if (_state.value.binding != editor.binding) return@launch
        result.fold(onSuccess = { id -> _state.update { it.copy(rateBusy = false, rateEditor = null,
            selectedRateSubmissionId = id, rateMessage = UiText.res(R.string.advice_rate_saved_locally)) } },
            onFailure = { error -> _state.update { it.copy(rateBusy = false,
                rateMessage = error.toUiText(R.string.advice_rate_save_failed)) } })
    }
}

fun BudgetAdviceViewModel.recoverRate(pending: PendingManualRateSubmission, drop: Boolean) {
    val binding = _state.value.binding ?: return
    if (_state.value.rateBusy) return
    _state.update { it.copy(rateBusy = true, rateMessage = null) }
    viewModelScope.launch {
        val result = repository.recoverRate(binding, pending, drop)
        if (_state.value.binding != binding) return@launch
        _state.update { it.copy(rateBusy = false, rateMessage = result.exceptionOrNull()?.toUiText(R.string.advice_rate_save_failed)) }
    }
}

fun BudgetAdviceViewModel.reviewRate(pending: PendingManualRateSubmission) {
    val request = pending.intent?.takeIf { it.supports(pending.row) }?.request ?: return
    openRate(MissingExchangeRateDto(request.currencyCode, request.homeCurrencyCode, request.rateDate), pending)
}

