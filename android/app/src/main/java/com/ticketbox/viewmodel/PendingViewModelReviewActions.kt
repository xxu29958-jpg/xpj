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

// ADR-0038 V6 fix — every sheet-opening path is "user moved to another
// action", so the prior 撤销 banner should disappear. Cheaper to gate here
// (the single sheet-opener surface) than to chase every individual write.
// Cancel timer + null undoableExpense via [dismissUndoable]; no-op when the
// banner is already absent.
fun PendingViewModel.openQuickCategory(expense: Expense) {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.QuickCategory(expense), message = null) }
}

fun PendingViewModel.openQuickMerchant(expense: Expense) {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.QuickMerchant(expense), message = null) }
}

fun PendingViewModel.openMissingAmount(expense: Expense) {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.MissingAmount(expense), message = null) }
}

fun PendingViewModel.openDuplicateAction(expense: Expense) {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    _uiState.update { it.copy(activeSheet = PendingSheet.Duplicate(expense), message = null) }
}

fun PendingViewModel.openBulkConfirm() {
    dismissUndoable()
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

fun PendingViewModel.saveAmountDraft(expenseId: Long, originalAmountMinor: Long) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (originalAmountMinor <= 0L) {
        _uiState.update { it.copy(message = "金额必须大于 0。") }
        return
    }
    val expense = _uiState.value.items.firstOrNull { it.id == expenseId }
    patchExpense(
        expenseId = expenseId,
        draft = blankDraft().copy(
            originalCurrencyCode = expense?.originalCurrencyCode,
            originalAmountMinor = originalAmountMinor,
        ),
        successMessage = "已保存金额",
        failureMessageFallback = "没有保存金额，请稍后再试。",
    )
}

fun PendingViewModel.saveAmountAndConfirm(expenseId: Long, originalAmountMinor: Long) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (originalAmountMinor <= 0L) {
        _uiState.update { it.copy(message = "金额必须大于 0。") }
        return
    }
    if (expenseId in _uiState.value.actionInProgressIds) return
    val expense = _uiState.value.items.firstOrNull { it.id == expenseId }
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                actionInProgressIds = it.actionInProgressIds + expenseId,
                message = null,
            )
        }
        repository.updateExpense(
            expenseId,
            blankDraft().copy(
                originalCurrencyCode = expense?.originalCurrencyCode,
                originalAmountMinor = originalAmountMinor,
            ),
            baseline = expense,
        )
            .onSuccess { updated ->
                _uiState.update { state ->
                    PendingUiStateReducer.afterUpdated(
                        current = state,
                        updated = updated,
                        closeSheet = false,
                        message = null,
                        clearInProgress = false,
                    )
                }
                // ADR-0041: post-PATCH ``updated.rowVersion`` is the
                // fresh token to confirm against (NOT the pre-PATCH baseline).
                repository.confirmExpense(expenseId, updated.rowVersion)
                    .onSuccess { confirmed ->
                        _uiState.update { state ->
                            PendingUiStateReducer.afterConfirmed(
                                current = state,
                                confirmed = confirmed,
                                message = "已保存并确认入账",
                            ).copy(activeSheet = PendingSheet.None)
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
            repository.confirmExpense(expense.id, expense.rowVersion)
                .onSuccess { confirmed ->
                    succeeded += 1
                    _uiState.update { current ->
                        PendingUiStateReducer.afterConfirmed(
                            current = current,
                            confirmed = confirmed,
                            message = null,
                        ).copy(
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
    val baseline = _uiState.value.items.firstOrNull { it.id == expenseId }
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                actionInProgressIds = it.actionInProgressIds + expenseId,
                message = null,
            )
        }
        repository.updateExpense(expenseId, draft, baseline)
            .onSuccess { updated ->
                _uiState.update { state ->
                    PendingUiStateReducer.afterUpdated(
                        current = state,
                        updated = updated,
                        closeSheet = true,
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
