package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal fun ExpenseFactViewModel.observeBillSplitSubmissions() {
    viewModelScope.launch {
        var previousBinding: LogicalSessionBinding? = null
        var completed = emptySet<Long>()
        combine(repository.observeBillSplitCreations(), uiState.map { it.correctionAccess?.binding }.distinctUntilChanged()) {
            observation, binding -> observation to binding
        }.collect { (observation, binding) ->
            if (previousBinding != binding) { completed = emptySet(); previousBinding = binding }
            val rows = observation.submissions.filter {
                observation.access?.binding == binding && binding != null && it.row.targetId == "expense:$expenseId"
            }
            val done = rows.filter { it.delivered }.map { it.row.id }.toSet()
            _uiState.update { state ->
                val receipts = rows.filter { it.delivered && it.row.id !in completed }.mapNotNull { it.invitation }
                state.copy(billSplitSubmissions = rows.filterNot { row -> row.delivered },
                    billSplitSent = state.billSplitSent + receipts.filter { receipt -> state.billSplitSent.none { it.publicId == receipt.publicId } })
            }
            if ((done - completed).isNotEmpty()) loadBillSplitSent()
            completed = done
        }
    }
}

internal fun ExpenseFactViewModel.hasPendingBillSplitCreation(): Boolean {
    if (_uiState.value.billSplitSubmissions.isEmpty()) return false
    _uiState.update { it.copy(message = UiText.res(R.string.bill_split_submission_pending), messageTone = MessageTone.Neutral) }
    return true
}

fun ExpenseFactViewModel.recoverBillSplitCreation(id: Long, drop: Boolean) {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    if (_uiState.value.billSplitRecoveryBusy) return
    _uiState.update { it.copy(billSplitRecoveryBusy = true) }
    viewModelScope.launch {
        val result = repository.recoverBillSplitCreation(binding, id, drop)
        if (_uiState.value.correctionAccess?.binding != binding) return@launch
        _uiState.update { it.copy(billSplitRecoveryBusy = false) }
        result.onFailure { error ->
            _uiState.update { it.copy(message = error.toUiText(R.string.expense_edit_bill_split_send_failed), messageTone = MessageTone.Danger) }
        }
        if (drop && result.isSuccess) { retryLoadExpense(); loadBillSplitSent() }
    }
}
