package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** 还款捕获草稿（迁移能力）：成功后由路由打开复核页。 */
fun ExpenseFactViewModel.createRepaymentDraftFromExpense() {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense ?: return
    viewModelScope.launch {
        _uiState.update { it.copy(repaymentDraftCreating = true) }
        repository.createRepaymentDraftFromExpense(expense)
            .onSuccess { draft ->
                _uiState.update {
                    it.copy(
                        repaymentDraftCreating = false,
                        openRepaymentDraftPublicId = draft.publicId,
                    )
                }
            }
            .onFailure { error ->
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
