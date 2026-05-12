package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * slice 3 M7 — PendingViewModel 的 Review 快速操作扩展。
 *
 * 与主 ViewModel 同文件包，使用 `internal` 字段访问。
 * 分类原因：保持 PendingViewModel.kt < 360 行（G2 闸门）。
 */

fun PendingViewModel.openQuickCategory(expense: Expense) {
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.QuickCategory(expense), message = null) }
}

fun PendingViewModel.openQuickMerchant(expense: Expense) {
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.QuickMerchant(expense), message = null) }
}

fun PendingViewModel.openMissingAmount(expense: Expense) {
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.MissingAmount(expense), message = null) }
}

fun PendingViewModel.openDuplicateAction(expense: Expense) {
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.Duplicate(expense), message = null) }
}

fun PendingViewModel.openBulkConfirm() {
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.BulkConfirm, message = null) }
}

fun PendingViewModel.closeSheet() {
    _uiState.update { it.copy(activeSheet = PendingSheet.None) }
}

fun PendingViewModel.saveQuickCategory(expenseId: Long, category: String) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    patchExpense(
        expenseId = expenseId,
        draft = blankDraft().copy(category = category.trim()),
        successMessage = "已更新分类",
        failureMessageFallback = "没有保存分类，请稍后再试。",
    )
}

fun PendingViewModel.saveQuickMerchant(expenseId: Long, merchant: String) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    val cleaned = merchant.trim()
    if (cleaned.isEmpty()) {
        _uiState.update { it.copy(message = "请输入商家名称。") }
        return
    }
    patchExpense(
        expenseId = expenseId,
        draft = blankDraft().copy(merchant = cleaned),
        successMessage = "已更新商家",
        failureMessageFallback = "没有保存商家，请稍后再试。",
    )
}

fun PendingViewModel.saveAmountDraft(expenseId: Long, amountCents: Long) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (amountCents <= 0L) {
        _uiState.update { it.copy(message = "金额必须大于 0。") }
        return
    }
    patchExpense(
        expenseId = expenseId,
        draft = blankDraft().copy(amountCents = amountCents),
        successMessage = "已保存金额",
        failureMessageFallback = "没有保存金额，请稍后再试。",
    )
}

fun PendingViewModel.saveAmountAndConfirm(expenseId: Long, amountCents: Long) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (amountCents <= 0L) {
        _uiState.update { it.copy(message = "金额必须大于 0。") }
        return
    }
    if (expenseId in _uiState.value.actionInProgressIds) return
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                actionInProgressIds = it.actionInProgressIds + expenseId,
                message = null,
            )
        }
        repository.updateExpense(expenseId, blankDraft().copy(amountCents = amountCents))
            .onSuccess { updated ->
                _uiState.update { state ->
                    state.copy(
                        items = state.items.map { if (it.id == updated.id) updated else it },
                    )
                }
                repository.confirmExpense(expenseId)
                    .onSuccess { confirmed ->
                        _uiState.update { state ->
                            state.copy(
                                items = state.items.filterNot { it.id == confirmed.id },
                                thumbnails = state.thumbnails - confirmed.id,
                                actionInProgressIds = state.actionInProgressIds - confirmed.id,
                                activeSheet = PendingSheet.None,
                                message = "已保存并确认入账",
                            )
                        }
                    }
                    .onFailure { error ->
                        _uiState.update {
                            it.copy(
                                actionInProgressIds = it.actionInProgressIds - expenseId,
                                message = error.message ?: "保存了金额但确认失败，请稍后再试。",
                            )
                        }
                    }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        actionInProgressIds = it.actionInProgressIds - expenseId,
                        message = error.message ?: "没有保存金额，请稍后再试。",
                    )
                }
            }
    }
}

fun PendingViewModel.confirmReadyExpenses() {
    if (blockReadOnlyWrite(closeSheet = true)) return
    val state = _uiState.value
    if (state.bulkConfirm.running) return
    val ready = state.items.filter {
        it.amountCents != null && !it.merchant.isNullOrBlank() && it.duplicateStatus != "suspected"
    }
    if (ready.isEmpty()) {
        _uiState.update { it.copy(message = "没有可直接确认的账单。") }
        return
    }
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                bulkConfirm = BulkConfirmRunState(total = ready.size, running = true),
                actionInProgressIds = it.actionInProgressIds + ready.map { e -> e.id }.toSet(),
                message = null,
            )
        }
        var succeeded = 0
        var failed = 0
        for (expense in ready) {
            repository.confirmExpense(expense.id)
                .onSuccess { confirmed ->
                    succeeded += 1
                    _uiState.update { current ->
                        current.copy(
                            items = current.items.filterNot { it.id == confirmed.id },
                            thumbnails = current.thumbnails - confirmed.id,
                            actionInProgressIds = current.actionInProgressIds - confirmed.id,
                            bulkConfirm = current.bulkConfirm.copy(succeeded = succeeded),
                        )
                    }
                }
                .onFailure {
                    failed += 1
                    _uiState.update { current ->
                        current.copy(
                            actionInProgressIds = current.actionInProgressIds - expense.id,
                            bulkConfirm = current.bulkConfirm.copy(failed = failed),
                        )
                    }
                }
        }
        _uiState.update {
            it.copy(
                bulkConfirm = BulkConfirmRunState(
                    total = ready.size,
                    succeeded = succeeded,
                    failed = failed,
                    running = false,
                ),
                activeSheet = PendingSheet.None,
                message = if (failed == 0) "已确认 $succeeded 条" else "确认完成：成功 $succeeded，失败 $failed",
            )
        }
    }
}

private fun blankDraft(): ExpenseDraft = ExpenseDraft(
    amountCents = null,
    merchant = null,
    category = null,
    note = null,
    expenseTime = null,
    tags = null,
    valueScore = null,
    regretScore = null,
)

private fun PendingViewModel.patchExpense(
    expenseId: Long,
    draft: ExpenseDraft,
    successMessage: String,
    failureMessageFallback: String,
) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (expenseId in _uiState.value.actionInProgressIds) return
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                actionInProgressIds = it.actionInProgressIds + expenseId,
                message = null,
            )
        }
        repository.updateExpense(expenseId, draft)
            .onSuccess { updated ->
                _uiState.update { state ->
                    state.copy(
                        items = state.items.map { if (it.id == updated.id) updated else it },
                        actionInProgressIds = state.actionInProgressIds - updated.id,
                        activeSheet = PendingSheet.None,
                        message = successMessage,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        actionInProgressIds = it.actionInProgressIds - expenseId,
                        message = error.message ?: failureMessageFallback,
                    )
                }
            }
    }
}
