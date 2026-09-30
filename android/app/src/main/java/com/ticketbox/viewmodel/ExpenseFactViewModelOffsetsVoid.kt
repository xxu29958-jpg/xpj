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
    if (blockReadOnlyWrite() || factInputUnavailable()) return
    if (restoreVoidInput(offset)) return
    _uiState.update { state ->
        state.copy(
            voidOffsetForm = VoidOffsetFormState(
                open = true,
                target = offset,
            ),
        )
    }
    keepVoidInput()
}

fun ExpenseFactViewModel.closeVoidOffsetSheet() {
    if (_uiState.value.voidOffsetForm.saving) return
    _uiState.update { it.copy(voidOffsetForm = it.voidOffsetForm.copy(open = false)) }
}

fun ExpenseFactViewModel.updateVoidOffsetReason(value: String) {
    if (!canEditFactInput("void:${_uiState.value.voidOffsetForm.target?.publicId}")) return
    _uiState.update {
        it.copy(voidOffsetForm = it.voidOffsetForm.copy(reason = value, submitError = null))
    }
    keepVoidInput()
}

fun ExpenseFactViewModel.reviewVoidOffsetDraft() {
    if (blockUnreadyFactWrite() || factInputOperationBusy()) return
    val state = _uiState.value
    val form = state.voidOffsetForm
    if (!form.open || state.factBundleLoadState != ExpenseDetailDataLoadState.Loaded) return
    val target = state.factBundle?.activeOffsets?.singleOrNull { it.publicId == form.target?.publicId } ?: return
    _uiState.update { it.copy(voidOffsetForm = form.copy(target = target, submitError = null)) }
    keepVoidInput(review = true)
}

fun ExpenseFactViewModel.canSubmitVoidOffset(): Boolean {
    val state = _uiState.value
    val form = state.voidOffsetForm
    if (!form.open || factInputOperationBusy()) return false
    if (state.readOnly || !state.authoritativeRootReady) return false
    if (factInputSession?.original("void:${form.target?.publicId}")?.binding != state.correctionAccess?.binding) return false
    if (state.factBundleLoadState == ExpenseDetailDataLoadState.Loaded && state.factBundle?.activeOffsets?.none {
        it.publicId == form.target?.publicId && it.rowVersion == form.target.rowVersion
    } == true) return false
    return form.target != null && form.reason.isNotBlank()
}

fun ExpenseFactViewModel.submitVoidOffset() {
    if (blockReadOnlyWrite()) return
    val state = _uiState.value
    val expense = state.expense ?: return
    val binding = state.correctionAccess?.binding ?: return
    val form = state.voidOffsetForm
    if (!form.open || factInputOperationBusy()) return
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
    if (!canSubmitVoidOffset()) return
    val session = factInputSession ?: return
    val inputKey = "void:${target.publicId}"
    _uiState.update { it.copy(voidOffsetForm = it.voidOffsetForm.copy(saving = true)) }
    viewModelScope.launch {
        if (_uiState.value.correctionAccess?.binding != binding || blockReadOnlyWrite()) return@launch
        _uiState.update { it.copy(voidOffsetForm = it.voidOffsetForm.copy(saving = true)) }
        session.ready(inputKey).fold(onSuccess = { repository.voidExpenseOffsetAllowingOffline(binding, expense, target, form.reason.trim(), it) },
            onFailure = { Result.failure(it) })
            .onSuccess {
                session.forget(inputKey)
                if (_uiState.value.correctionAccess?.binding != binding) return@onSuccess
                publishOffsetQueued(isVoid = true)
            }
            .onFailure { error ->
                if (_uiState.value.correctionAccess?.binding == binding) publishOffsetFailure(error, isVoid = true)
            }
    }
}
