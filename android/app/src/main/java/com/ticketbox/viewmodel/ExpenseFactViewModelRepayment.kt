package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.canCreateRepaymentDraft
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** 还款捕获草稿（迁移能力）：成功后由路由打开复核页。 */
fun ExpenseFactViewModel.createRepaymentDraftFromExpense() {
    if (blockUnreadyFactWrite()) return
    val state = _uiState.value
    val expense = state.expense ?: return
    val binding = state.correctionAccess?.binding ?: return
    if (state.repaymentDraftCreating || !expense.canCreateRepaymentDraft(state.readOnly)) return
    _uiState.update { it.copy(repaymentDraftCreating = true) }
    viewModelScope.launch {
        if (binding != _uiState.value.correctionAccess?.binding) return@launch
        if (blockUnreadyFactWrite(expense.rowVersion)) {
            _uiState.update { it.copy(repaymentDraftCreating = false) }
            return@launch
        }
        repository.createRepaymentDraftFromExpense(binding, expense)
            .onSuccess { draft ->
                if (binding != _uiState.value.correctionAccess?.binding) return@onSuccess
                _uiState.update {
                    it.copy(
                        repaymentDraftCreating = false,
                        openRepaymentDraftPublicId = draft.publicId,
                    )
                }
            }
            .onFailure { error ->
                if (binding != _uiState.value.correctionAccess?.binding) return@onFailure
                _uiState.update {
                    it.copy(
                        repaymentDraftCreating = false,
                        message = error.toUiText(R.string.expense_edit_repayment_draft_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

fun ExpenseFactViewModel.consumeOpenRepaymentDraftPublicId(): String? {
    val publicId = _uiState.value.openRepaymentDraftPublicId
    if (publicId != null) {
        _uiState.update { it.copy(openRepaymentDraftPublicId = null) }
    }
    return publicId
}
