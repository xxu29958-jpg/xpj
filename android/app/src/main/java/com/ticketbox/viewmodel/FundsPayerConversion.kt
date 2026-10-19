package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import androidx.compose.runtime.snapshotFlow
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first

internal fun FundsViewModel.needsPayerQuote(old: FundsInput, changed: FundsInput): Boolean =
    changed.mode == "repay" && (changed.payerCurrency != old.payerCurrency ||
        (changed.payerId != old.payerId && old.paid.isBlank()) ||
        changed.principal != old.principal || changed.date != old.date) &&
        (changed.payerCurrency != old.payerCurrency || old.paid.isBlank() || old.paid == suggestedPayerAmount ||
            changed.payerCurrency == changed.currency)

private fun FundsUiState.acceptsPayerQuote(input: FundsInput, latest: FundsInput): Boolean =
    access?.binding == input.binding && access.canModify && !task.frozen && !busy &&
        latest.key == input.key && latest.payerId == input.payerId && latest.payerCurrency == input.payerCurrency &&
        latest.principal == input.principal && latest.date == input.date && latest.paid.isBlank()

/** A rate suggests the editable deduction; only the existing confirmation can record it. */
internal fun FundsViewModel.quotePayerAmount(input: FundsInput) {
    payerQuoteJob?.cancel()
    suggestedPayerAmount = null
    if (input.payerCurrency == input.currency) { suggestedPayerAmount = input.paid; return }
    if (input.payerCurrency.isBlank() || input.principal.toBigDecimalOrNull() == null ||
        runCatching { java.time.LocalDate.parse(input.date) }.isFailure) return
    payerQuoteJob = viewModelScope.launch {
        val result = repository.convertPayerAmount(input)
        // Submission can reject the still-empty deduction. Keep its matching quote until editing resumes.
        snapshotFlow { state.value.busy }.first { !it }
        val current = state.value
        val latest = current.task.input ?: return@launch
        if (!current.acceptsPayerQuote(input, latest)) return@launch
        val amount = result.getOrNull()?.convertedAmount
        if (amount == null) {
            mutable.value = current.copy(error = current.error ?: result.exceptionOrNull()?.toUiText()
                ?: UiText.res(R.string.advice_reference_missing_date, input.date))
        } else {
            val updated = latest.copy(paid = amount)
            suggestedPayerAmount = amount
            mutable.value = current.copy(task = current.task.copy(input = updated))
            save(updated)
        }
    }
}
