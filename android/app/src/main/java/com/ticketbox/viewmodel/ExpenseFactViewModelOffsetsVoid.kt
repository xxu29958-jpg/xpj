package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Refund/Chargeback/Reversal 纵向片：撤销（void）确认表单。
 *
 * 边界（共同冻结）：void 只作用于服务端已持久化的 active offset；排队中的
 * create/void intent 没有「取消排队」入口，其表达与放弃归既有 Outbox surface，
 * 本片不承诺「撤销排队中的退款」。撤销不是删除：记录保留在 offset 历史里。
 */

fun ExpenseFactViewModel.openVoidOffsetSheet(offset: ExpenseOffsetFact) {
    if (blockReadOnlyWrite()) return
    _uiState.update { state ->
        state.copy(
            voidOffsetForm = VoidOffsetFormState(
                open = true,
                target = offset,
                conflictMessage = UiText.res(R.string.expense_offset_conflict)
                    .takeIf { state.offsetCommandsBlockedUntilRefresh },
                refreshingAfterConflict = state.offsetCommandsBlockedUntilRefresh,
            ),
        )
    }
}

fun ExpenseFactViewModel.closeVoidOffsetSheet() {
    _uiState.update { it.copy(voidOffsetForm = VoidOffsetFormState()) }
}

fun ExpenseFactViewModel.updateVoidOffsetReason(value: String) {
    _uiState.update {
        it.copy(voidOffsetForm = it.voidOffsetForm.copy(reason = value, submitError = null))
    }
}

fun ExpenseFactViewModel.canSubmitVoidOffset(): Boolean {
    val state = _uiState.value
    val form = state.voidOffsetForm
    if (state.offsetCommandsBlockedUntilRefresh) return false
    if (!form.open || form.saving || form.refreshingAfterConflict) return false
    return form.target != null && form.reason.isNotBlank()
}

fun ExpenseFactViewModel.submitVoidOffset() {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense ?: return
    val form = _uiState.value.voidOffsetForm
    val target = form.target ?: return
    if (form.reason.isBlank()) {
        _uiState.update {
            it.copy(
                voidOffsetForm = it.voidOffsetForm.copy(
                    submitError = UiText.res(R.string.expense_offset_void_reason_required),
                ),
            )
        }
        return
    }
    viewModelScope.launch {
        _uiState.update { it.copy(voidOffsetForm = it.voidOffsetForm.copy(saving = true)) }
        repository.voidExpenseOffsetAllowingOffline(expense, target, form.reason.trim())
            .onSuccess { outcome ->
                publishOffsetOutcome(outcome, R.string.expense_offset_void_success)
            }
            .onFailure { error -> publishOffsetFailure(error, isVoid = true) }
    }
}
